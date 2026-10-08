"""Mongo persistence for paper portfolios and trade orders."""

from __future__ import annotations

import os
from threading import Lock
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from app.trading.constants import MAX_STORED_TRADE_ORDERS
from app.trading.dto import OrderRequestDTO, PortfolioPatchDTO
from dto.news import NewsEventDTO
from dto.stock import TickerGraphDTO
from app.trading.model import (
    Portfolio,
    PortfolioConfig,
    PortfolioStatus,
    PendingRebalance,
    PendingRebalanceStatus,
    PortfolioValuePoint,
    TradeOrder,
)
from constants import NewsAnalysisStatus
from models.documents import NewsEvent
from services.redis.cache import cached_read, invalidates_read_cache

_orders_retention_checked = False
_repository_setup_lock = Lock()
_repository_setup_complete = False


def _mongo_safe(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, dict):
        return {key: _mongo_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mongo_safe(item) for item in value]
    return value


def _utc_datetime(value: datetime) -> datetime:
    """Normalize Mongo's naive UTC datetimes and aware application datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _plan_session_key(value: datetime) -> datetime:
    return _utc_datetime(value).replace(microsecond=0)


class TradingRepository:
    def __init__(self, client: MongoClient | None = None) -> None:
        self.client = client or MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
        database = self.client[os.getenv("MONGO_DATABASE", "financial_nlp")]
        self.portfolios = database["trading_portfolios"]
        self.orders = database["trading_orders"]
        self.tickers = database["tickers"]
        self.news_events = database["news_events"]
        self.pending_rebalances = database["trading_pending_rebalances"]
        # This repository is opened for every API request. Keep index setup and
        # the one-off retention sweep out of the hot path after process start.
        global _orders_retention_checked, _repository_setup_complete
        if not _repository_setup_complete:
            with _repository_setup_lock:
                if not _repository_setup_complete:
                    self.portfolios.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
                    self.orders.create_index([("portfolio_id", ASCENDING), ("created_at", DESCENDING)])
                    self.orders.create_index([("event_id", ASCENDING), ("portfolio_id", ASCENDING)], sparse=True)
                    self.orders.create_index([("event_ids", ASCENDING), ("portfolio_id", ASCENDING)], sparse=True)
                    self.pending_rebalances.create_index(
                        [("status", ASCENDING), ("scheduled_for", ASCENDING)],
                        name="pending_rebalances_due",
                    )
                    self.pending_rebalances.create_index(
                        [("portfolio_id", ASCENDING), ("status", ASCENDING)],
                        name="pending_rebalances_portfolio",
                    )
                    self._merge_duplicate_pending_rebalances()
                    self.pending_rebalances.create_index(
                        [("portfolio_id", ASCENDING), ("scheduled_for", ASCENDING)],
                        unique=True,
                        partialFilterExpression={"status": PendingRebalanceStatus.PENDING.value},
                        name="pending_portfolio_session_unique",
                    )
                    if not _orders_retention_checked:
                        self.prune_oldest_orders()
                        _orders_retention_checked = True
                    _repository_setup_complete = True

    def _merge_duplicate_pending_rebalances(self) -> None:
        """Coalesce legacy duplicate plans for one portfolio/session, preserving audit rows."""
        groups: dict[tuple[str, datetime], list[dict]] = {}
        for row in self.pending_rebalances.find({"status": PendingRebalanceStatus.PENDING.value}).sort(
            [("decision_at", ASCENDING), ("_id", ASCENDING)]
        ):
            key = (row["portfolio_id"], _plan_session_key(row["scheduled_for"]))
            groups.setdefault(key, []).append(row)
        for (_portfolio_id, _session), plans in groups.items():
            if len(plans) < 2:
                continue
            canonical = plans[0]
            targets: dict[str, float] = {}
            event_ids: list[str] = []
            ticker_event_ids: dict[str, list[str]] = {}
            for plan in plans:
                targets.update(plan.get("target_weights", {}))
                event_ids.extend(plan.get("event_ids", []))
                if plan.get("event_id"):
                    event_ids.append(plan["event_id"])
                for ticker, ids in plan.get("ticker_event_ids", {}).items():
                    ticker_event_ids.setdefault(ticker, []).extend(ids)
            event_ids = list(dict.fromkeys(event_ids))
            ticker_event_ids = {ticker: list(dict.fromkeys(ids)) for ticker, ids in ticker_event_ids.items()}
            self.pending_rebalances.update_one(
                {"_id": canonical["_id"]},
                {"$set": {"target_weights": targets, "event_ids": event_ids,
                          "ticker_event_ids": ticker_event_ids, "updated_at": datetime.now(timezone.utc)}},
            )
            for duplicate in plans[1:]:
                self.pending_rebalances.update_one(
                    {"_id": duplicate["_id"]},
                    {"$set": {"status": PendingRebalanceStatus.CANCELLED.value,
                              "last_error": f"Merged into plan {canonical['_id']} for the same market session.",
                              "updated_at": datetime.now(timezone.utc)}},
                )

    @invalidates_read_cache("trading")
    def create_portfolio(self, *, name: str, initial_capital: float, config: PortfolioConfig | None = None,
                         news_enabled: bool = False) -> Portfolio:
        portfolio = Portfolio(
            name=name,
            initial_capital=initial_capital,
            cash=initial_capital,
            portfolio_value=initial_capital,
            peak_value=initial_capital,
            news_enabled=news_enabled,
            config=config or {},
        )
        document = portfolio.model_dump(mode="python", by_alias=True)
        document["_id"] = ObjectId(portfolio.id)
        self.portfolios.insert_one(document)
        return portfolio

    @cached_read("trading-portfolio", 15)
    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        if not ObjectId.is_valid(portfolio_id):
            return None
        row = self.portfolios.find_one({"_id": ObjectId(portfolio_id)})
        return Portfolio.model_validate(row) if row else None

    @cached_read("trading-active-portfolios", 15)
    def get_active_portfolios(self) -> list[Portfolio]:
        return [Portfolio.model_validate(row) for row in self.portfolios.find({"status": PortfolioStatus.ACTIVE.value})]

    @cached_read("trading-portfolios", 15)
    def list_portfolios(self, limit: int = 100) -> list[Portfolio]:
        return [Portfolio.model_validate(row) for row in self.portfolios.find().sort("created_at", DESCENDING).limit(limit)]

    @invalidates_read_cache("trading")
    def patch_portfolio(self, portfolio_id: str, patch: PortfolioPatchDTO) -> Portfolio | None:
        if not ObjectId.is_valid(portfolio_id):
            return None
        updates = patch.model_dump(mode="python", exclude_unset=True, exclude_none=True)
        if "config" in updates:
            current = self.get_portfolio(portfolio_id)
            if current is None:
                return None
            changes = patch.config.model_dump(exclude_unset=True, exclude_none=True)
            updates["config"] = current.config.model_copy(update=changes).model_dump(mode="python")
        if updates:
            updates["updated_at"] = datetime.now(timezone.utc)
            self.portfolios.update_one({"_id": ObjectId(portfolio_id)}, {"$set": updates})
        return self.get_portfolio(portfolio_id)

    @invalidates_read_cache("trading")
    def save_portfolio(self, portfolio: Portfolio) -> None:
        portfolio.updated_at = datetime.now(timezone.utc)
        self.portfolios.update_one(
            {"_id": ObjectId(portfolio.id)},
            {"$set": _mongo_safe(portfolio.model_dump(mode="python", by_alias=True, exclude={"id", "created_at"}))},
        )

    @invalidates_read_cache("trading")
    def insert_order(self, request: OrderRequestDTO, *, portfolio: Portfolio, price: float,
                     transaction_cost: float, quantity: int, event_id: str | None = None,
                     event_ids: list[str] | None = None, created_at: datetime | None = None) -> TradeOrder:
        gross = price * quantity
        cash_change = -(gross + transaction_cost) if request.side.value == "buy" else gross - transaction_cost
        order = TradeOrder(
            portfolio_id=portfolio.id,
            ticker_id=request.ticker_id,
            side=request.side,
            quantity=quantity,
            price=price,
            gross_value=gross,
            transaction_cost=transaction_cost,
            net_cash_change=cash_change,
            event_id=event_id or request.event_id,
            event_ids=list(dict.fromkeys(event_ids or ([event_id or request.event_id] if event_id or request.event_id else []))),
            reason=request.reason,
            created_at=created_at or datetime.now(timezone.utc),
        )
        self.orders.insert_one(order.model_dump(mode="python", by_alias=True))
        portfolio.order_count += 1
        self._prune_orders_if_needed()
        return order

    @invalidates_read_cache("trading")
    def insert_orders(self, orders: list[TradeOrder]) -> None:
        if orders:
            self.orders.insert_many([item.model_dump(mode="python", by_alias=True) for item in orders], ordered=False)
            self._prune_orders_if_needed()

    def _prune_orders_if_needed(self) -> int:
        if self.orders.estimated_document_count() <= MAX_STORED_TRADE_ORDERS:
            return 0
        return self.prune_oldest_orders()

    def prune_oldest_orders(self) -> int:
        """Keep the newest paper order history within its storage bound."""
        excess = self.orders.count_documents({}) - MAX_STORED_TRADE_ORDERS
        if excess <= 0:
            return 0
        oldest_ids = [row["_id"] for row in self.orders.find({}, {"_id": 1})
                      .sort([("created_at", ASCENDING), ("_id", ASCENDING)]).limit(excess)]
        return self.orders.delete_many({"_id": {"$in": oldest_ids}}).deleted_count if oldest_ids else 0

    @cached_read("trading-orders", 15)
    def list_orders(self, portfolio_id: str, limit: int = 100, *, offset: int = 0,
                    since: datetime | None = None, ticker_id: str | None = None) -> list[TradeOrder]:
        query: dict[str, object] = {"portfolio_id": portfolio_id}
        if since is not None:
            query["created_at"] = {"$gte": since}
        if ticker_id:
            query["ticker_id"] = ticker_id.strip().upper()
        return [TradeOrder.model_validate(row) for row in self.orders.find(query)
                .sort("created_at", DESCENDING).skip(offset).limit(limit)]

    @cached_read("trading-order-count", 15)
    def count_orders(self, portfolio_id: str, *, since: datetime | None = None,
                     ticker_id: str | None = None) -> int:
        query: dict[str, object] = {"portfolio_id": portfolio_id}
        if since is not None:
            query["created_at"] = {"$gte": since}
        if ticker_id:
            query["ticker_id"] = ticker_id.strip().upper()
        return self.orders.count_documents(query)

    def list_event_activity(self, event_ids: list[str]) -> tuple[list[TradeOrder], list[PendingRebalance]]:
        """Resolve all saved trade and rebalance records linked to a set of news events."""
        ids = list(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
        if not ids:
            return [], []
        query = {"$or": [{"event_id": {"$in": ids}}, {"event_ids": {"$in": ids}}]}
        orders = [TradeOrder.model_validate(row) for row in self.orders.find(query).sort("created_at", DESCENDING)]
        # Some older plans only persisted the per-ticker attribution map. Query
        # both representations so event drawers and the ledger can still find
        # those plans (including after they have been filled).
        plan_query = {"$or": [
            {"event_ids": {"$in": ids}},
            {"$expr": {"$gt": [
                {"$size": {"$filter": {
                    "input": {"$objectToArray": {"$ifNull": ["$ticker_event_ids", {}]}},
                    "as": "ticker_link",
                    "cond": {"$gt": [
                        {"$size": {"$setIntersection": [
                            {"$ifNull": ["$$ticker_link.v", []]}, ids,
                        ]}},
                        0,
                    ]},
                }}},
                0,
            ]}},
        ]}
        plans = [PendingRebalance.model_validate(row) for row in self.pending_rebalances.find(plan_query).sort("decision_at", DESCENDING)]
        return orders, plans

    def append_value_point(self, portfolio: Portfolio, *, timestamp: datetime | None = None) -> None:
        current_time = timestamp or datetime.now(timezone.utc)
        total_value = portfolio.cash + sum(position.market_value for position in portfolio.positions)
        portfolio.portfolio_value = total_value
        portfolio.peak_value = max(portfolio.peak_value, total_value)
        point = PortfolioValuePoint(
            timestamp=current_time,
            total_value=total_value,
            cash=portfolio.cash,
            invested_value=total_value - portfolio.cash,
        )
        if portfolio.value_history and portfolio.value_history[-1].timestamp.date() == current_time.date():
            portfolio.value_history[-1] = point
        else:
            portfolio.value_history.append(point)
        portfolio.value_history = portfolio.value_history[-3650:]
        self.save_portfolio(portfolio)

    @cached_read("trading-ticker-row", 10)
    def get_ticker_row(self, ticker_id: str) -> dict[str, object] | None:
        return self.tickers.find_one(
            {"ticker_name.ticker_id": ticker_id},
            {"ticker_score": 1, "ticker_graph": 1, "ticker_name": 1},
        )

    @cached_read("trading-ticker-graph", 10)
    def get_ticker_graph(self, ticker_id: str) -> TickerGraphDTO | None:
        row = self.tickers.find_one(
            {"ticker_name.ticker_id": ticker_id},
            {"ticker_graph": 1, "_id": 0},
        )
        if not row or not row.get("ticker_graph"):
            return None
        return TickerGraphDTO.model_validate(row["ticker_graph"])

    def get_news_event(self, event_id: str) -> NewsEventDTO | None:
        if not ObjectId.is_valid(event_id):
            return None
        row = self.news_events.find_one({"_id": ObjectId(event_id)})
        return NewsEvent.model_validate(row).to_dto() if row else None

    def get_completed_news_events(
        self, portfolio_id: str, after: datetime, through: datetime, *, max_per_day: int = 10,
    ) -> list[tuple[NewsEventDTO, str]]:
        """Load chronological, completed events within the startup catch-up cap."""
        rows = list(self.news_events.find({
            "event_timestamp": {"$gt": after, "$lte": through},
            "metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value,
        }).sort("event_timestamp", ASCENDING))
        portfolio = self.get_portfolio(portfolio_id)
        already_applied = set(portfolio.processed_news_event_ids) if portfolio else set()
        selected: list[tuple[NewsEventDTO, str]] = []
        counts: dict[object, int] = {}
        new_york = ZoneInfo("America/New_York")
        for row in rows:
            event_id = str(row["_id"])
            if event_id in already_applied:
                continue
            event = NewsEvent.model_validate(row).to_dto()
            day = event.event_datetime.astimezone(new_york).date()
            if counts.get(day, 0) >= max_per_day:
                continue
            counts[day] = counts.get(day, 0) + 1
            selected.append((event, event_id))
        return selected

    def queue_rebalance(self, *, portfolio_id: str, event_id: str | None, decision_at: datetime,
                        scheduled_for: datetime, reason: str,
                        target_weights: dict[str, float], event_ids: list[str] | None = None,
                        ticker_event_ids: dict[str, list[str]] | None = None) -> PendingRebalance:
        """Persist a next-session target, merging same-day signals into one plan."""
        current = self.pending_rebalances.find_one({
            "portfolio_id": portfolio_id,
            "status": PendingRebalanceStatus.PENDING.value,
        }, sort=[("scheduled_for", ASCENDING)])
        if current and _plan_session_key(current["scheduled_for"]) == _plan_session_key(scheduled_for):
            merged = dict(current.get("target_weights", {}))
            merged.update(target_weights)
            merged_event_ids = list(dict.fromkeys([
                *current.get("event_ids", []), *(event_ids or []), *([event_id] if event_id else []),
            ]))
            merged_ticker_event_ids = {
                ticker: list(dict.fromkeys(ids))
                for ticker, ids in current.get("ticker_event_ids", {}).items()
            }
            for ticker, ids in (ticker_event_ids or {}).items():
                merged_ticker_event_ids[ticker] = list(dict.fromkeys([
                    *merged_ticker_event_ids.get(ticker, []), *ids,
                ]))
            self.pending_rebalances.update_one(
                {"_id": current["_id"]},
                {"$set": {"target_weights": merged, "event_ids": merged_event_ids,
                          "ticker_event_ids": merged_ticker_event_ids,
                          "updated_at": datetime.now(timezone.utc), "reason": reason}},
            )
            current = self.pending_rebalances.find_one({"_id": current["_id"]})
            return PendingRebalance.model_validate(current)
        pending = PendingRebalance(
            _id=str(ObjectId()),
            portfolio_id=portfolio_id,
            event_ids=list(dict.fromkeys([*(event_ids or []), *([event_id] if event_id else [])])),
            ticker_event_ids=ticker_event_ids or {},
            decision_at=decision_at,
            scheduled_for=scheduled_for,
            reason=reason,
            target_weights=target_weights,
            news_filter_applied=reason == "news_sentiment",
        )
        try:
            self.pending_rebalances.insert_one(pending.model_dump(mode="python", by_alias=True))
        except DuplicateKeyError:
            # A second news source may have created this same session plan
            # between our lookup and insert; retry now that it is visible.
            return self.queue_rebalance(
                portfolio_id=portfolio_id, event_id=event_id, event_ids=event_ids,
                ticker_event_ids=ticker_event_ids, decision_at=decision_at,
                scheduled_for=scheduled_for, reason=reason, target_weights=target_weights,
            )
        return pending

    def update_pending_news_targets(self, pending_id: str, *, target_weights: dict[str, float],
                                    event_ids: list[str], ticker_event_ids: dict[str, list[str]]) -> None:
        self.pending_rebalances.update_one(
            {"_id": pending_id, "status": PendingRebalanceStatus.PENDING.value},
            {"$set": {"target_weights": target_weights, "event_ids": event_ids,
                      "ticker_event_ids": ticker_event_ids, "news_filter_applied": True,
                      "updated_at": datetime.now(timezone.utc)}},
        )

    def cancel_pending_rebalance(self, pending_id: str, *, reason: str) -> None:
        self.pending_rebalances.update_one(
            {"_id": pending_id, "status": PendingRebalanceStatus.PENDING.value},
            {"$set": {"status": PendingRebalanceStatus.CANCELLED.value,
                      "last_error": reason[:500], "updated_at": datetime.now(timezone.utc)}},
        )

    def get_pending_rebalances(self, *, due_before: datetime | None = None,
                               portfolio_id: str | None = None) -> list[PendingRebalance]:
        query: dict[str, object] = {"status": PendingRebalanceStatus.PENDING.value}
        if due_before is not None:
            query["scheduled_for"] = {"$lte": due_before}
        if portfolio_id is not None:
            query["portfolio_id"] = portfolio_id
        return [PendingRebalance.model_validate(row) for row in self.pending_rebalances.find(query).sort("scheduled_for", ASCENDING)]

    def get_rebalance_history(self, portfolio_id: str, limit: int = 100) -> list[PendingRebalance]:
        rows = self.pending_rebalances.find({
            "portfolio_id": portfolio_id,
            "status": {"$in": [PendingRebalanceStatus.PENDING.value, PendingRebalanceStatus.FILLED.value]},
        }).sort("scheduled_for", DESCENDING).limit(limit)
        return [PendingRebalance.model_validate(row) for row in rows]

    def finish_pending_rebalance(self, pending_id: str, *, executed_at: datetime | None = None,
                                 error: str | None = None) -> None:
        query = {"_id": pending_id, "status": PendingRebalanceStatus.PENDING.value}
        changes: dict[str, object] = {"updated_at": datetime.now(timezone.utc)}
        if error:
            changes.update({"last_error": error[:500]})
            self.pending_rebalances.update_one(query, {"$set": changes, "$inc": {"attempts": 1}})
            return
        changes.update({"status": PendingRebalanceStatus.FILLED.value, "executed_at": executed_at or datetime.now(timezone.utc)})
        self.pending_rebalances.update_one(
            query,
            {"$set": changes, "$unset": {"last_error": ""}, "$inc": {"attempts": 1}},
        )

    def close(self) -> None:
        self.client.close()
