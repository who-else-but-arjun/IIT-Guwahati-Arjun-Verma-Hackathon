"""Paper order execution, portfolio valuation, and news-driven rebalancing."""

from __future__ import annotations

import logging
import math
from datetime import datetime, time, timezone

import numpy as np
import pandas as pd

from app.trading.dto import OrderRequestDTO, PortfolioPatchDTO
from app.trading.model import (
    OrderSide,
    Portfolio,
    PortfolioConfig,
    PortfolioDailyMetrics,
    PortfolioPosition,
    PortfolioStatus,
    TradeOrder,
)
from app.trading.repository import TradingRepository
from app.trading.services.strategy import (
    load_market_data,
    mean_variance_weights,
    rank_residual_strength,
    rebalance_trigger,
)
from app.trading.constants import (GRAPH_PROPAGATION_SCALE, MAX_NEWS_TICKERS_PER_PLAN,
                                   MIN_NEWS_IMPACT_SCORE, MIN_NEWS_SENTIMENT_MAGNITUDE, SP100_TICKERS)
from app.trading.services.market_data import (
    NEW_YORK, current_metric_session, download_latest_prices, download_open_prices_on,
    next_session_open,
)

logger = logging.getLogger(__name__)


def _same_instant(left: datetime, right: datetime) -> bool:
    left_utc = left.replace(tzinfo=timezone.utc) if left.tzinfo is None else left.astimezone(timezone.utc)
    right_utc = right.replace(tzinfo=timezone.utc) if right.tzinfo is None else right.astimezone(timezone.utc)
    return left_utc.replace(microsecond=0) == right_utc.replace(microsecond=0)


class PortfolioService:
    def __init__(self, repository: TradingRepository | None = None) -> None:
        self.repository = repository or TradingRepository()
        self._owns_repository = repository is None

    def create_portfolio(self, *, name: str, initial_capital: float, config: PortfolioConfig | None = None) -> Portfolio:
        return self.repository.create_portfolio(name=name, initial_capital=initial_capital, config=config)

    def get_details(self, portfolio_id: str) -> tuple[Portfolio | None, list]:
        portfolio = self.repository.get_portfolio(portfolio_id)
        if portfolio is None:
            return None, []
        self._refresh_market_values(portfolio)
        return portfolio, self.repository.list_orders(portfolio.id)

    def patch_portfolio(self, portfolio_id: str, patch: PortfolioPatchDTO):
        return self.repository.patch_portfolio(portfolio_id, patch)

    def place_order(self, portfolio_id: str, request: OrderRequestDTO):
        portfolio = self._active_portfolio(portfolio_id)
        if request.ticker_id not in SP100_TICKERS:
            raise ValueError(f"{request.ticker_id} is not in the configured S&P 100 universe.")
        price = self._latest_prices([request.ticker_id])[request.ticker_id]
        order = self._execute_at_price(portfolio, request, price)
        prices = self._latest_prices([position.ticker_id for position in portfolio.positions])
        self._refresh_positions(portfolio, prices)
        self._record_daily_metrics(portfolio)
        self.repository.save_portfolio(portfolio)
        return portfolio, order

    def rebalance(self, portfolio_id: str, *, force: bool = False) -> tuple[Portfolio, str | None]:
        portfolio = self._active_portfolio(portfolio_id)
        if self.repository.get_pending_rebalances(portfolio_id=portfolio_id):
            return portfolio, None
        closes, volumes, benchmark = load_market_data(portfolio)
        now = pd.Timestamp.now(tz="UTC")
        trigger = "manual" if force else rebalance_trigger(portfolio, volumes, now)
        if trigger is None:
            return portfolio, None
        ranked = rank_residual_strength(
            closes,
            benchmark,
            lookback_days=portfolio.config.rs_lookback_days,
            candidate_count=portfolio.config.candidate_count,
            portfolio_size=portfolio.config.portfolio_size,
        )
        if not ranked:
            raise RuntimeError("Not enough overlapping market history to rank the S&P 100.")
        selected = [ticker for ticker, _ in ranked]
        target_weights = mean_variance_weights(
            closes,
            selected,
            max_position_weight=portfolio.config.max_position_weight,
            lookback_days=portfolio.config.rs_lookback_days,
        )
        decision_at = datetime.now(timezone.utc)
        scheduled_for = next_session_open(decision_at)
        self.repository.queue_rebalance(
            portfolio_id=portfolio.id,
            event_id=None,
            decision_at=decision_at,
            scheduled_for=scheduled_for,
            reason=f"strategy:{trigger}",
            target_weights=target_weights,
        )
        portfolio.last_rebalance_trigger = trigger
        self.repository.save_portfolio(portfolio)
        return portfolio, trigger

    def handle_news_event(self, event_id: str, ticker_ids: list[str]) -> None:
        """Create event-linked target changes scaled by event impact and ticker relevance."""
        event = self.repository.get_news_event(event_id)
        if event is None or event.sentiment is None:
            raise LookupError(f"Analyzed news event {event_id} is unavailable for trading.")
        affected = set(ticker_ids)
        direct = {item.ticker_id for item in event.relevant_tickers}
        signals: dict[str, float] = {}
        impact = event.sentiment.impact_score
        for ticker in event.relevant_tickers:
            if ticker.relevance_score < 0.55:
                continue
            contribution = event.sentiment.score * impact * ticker.relevance_score
            if ticker.ticker_id in affected:
                signals[ticker.ticker_id] = signals.get(ticker.ticker_id, 0.0) + contribution
            graph = self.repository.get_ticker_graph(ticker.ticker_id)
            if graph is None:
                continue
            for neighbor, correlation in graph.correlations.items():
                if neighbor in direct or neighbor not in affected:
                    continue
                propagated = contribution * correlation * GRAPH_PROPAGATION_SCALE
                signals[neighbor] = signals.get(neighbor, 0.0) + propagated

        for portfolio in self.repository.get_active_portfolios():
            if not portfolio.news_enabled:
                continue
            if event_id in portfolio.processed_news_event_ids:
                continue
            impact_score = event.sentiment.impact_score
            sentiment_score = event.sentiment.score
            if (impact_score is None or float(impact_score) < max(MIN_NEWS_IMPACT_SCORE, portfolio.config.min_news_impact_score)
                    or sentiment_score is None or abs(float(sentiment_score)) < MIN_NEWS_SENTIMENT_MAGNITUDE):
                portfolio.last_news_event_id = event_id
                portfolio.processed_news_event_ids = (portfolio.processed_news_event_ids + [event_id])[-4096:]
                self.repository.save_portfolio(portfolio)
                continue
            scheduled_for = next_session_open(datetime.now(timezone.utc))
            existing_plans = self.repository.get_pending_rebalances(portfolio_id=portfolio.id)
            existing_plan = next(
                (plan for plan in existing_plans if _same_instant(plan.scheduled_for, scheduled_for)), None,
            )
            targets = (
                dict(existing_plan.target_weights) if existing_plan else
                {position.ticker_id: position.weight for position in portfolio.positions}
            )
            ticker_event_ids: dict[str, list[str]] = {}
            touched = set(existing_plan.ticker_event_ids) if existing_plan else set()
            for ticker_id, signal in sorted(signals.items(), key=lambda item: abs(item[1]), reverse=True):
                threshold = max(portfolio.config.sentiment_delta_threshold, 0.18)
                if ticker_id not in SP100_TICKERS or abs(signal) < threshold:
                    continue
                if ticker_id not in touched and len(touched) >= MAX_NEWS_TICKERS_PER_PLAN:
                    continue
                current = targets.get(ticker_id, 0.0)
                weight_delta = min(
                    portfolio.config.news_weight_step,
                    0.01,
                    portfolio.config.max_position_weight * abs(signal),
                )
                if signal > 0:
                    updated = min(portfolio.config.max_position_weight, current + weight_delta)
                elif signal < 0:
                    updated = max(0.0, current - weight_delta)
                else:
                    continue
                if updated != current:
                    targets[ticker_id] = updated
                    ticker_event_ids[ticker_id] = [event_id]
                    touched.add(ticker_id)

            if ticker_event_ids:
                decision_at = datetime.now(timezone.utc)
                self.repository.queue_rebalance(
                    portfolio_id=portfolio.id,
                    event_id=event_id,
                    event_ids=[event_id],
                    ticker_event_ids=ticker_event_ids,
                    decision_at=decision_at,
                    scheduled_for=scheduled_for,
                    reason="news_sentiment",
                    target_weights=targets,
                )
            portfolio.last_news_event_id = event_id
            portfolio.processed_news_event_ids = (portfolio.processed_news_event_ids + [event_id])[-4096:]
            self.repository.save_portfolio(portfolio)

    def run_scheduled_rebalances(self) -> None:
        for portfolio in self.repository.get_active_portfolios():
            try:
                self.rebalance(portfolio.id)
            except Exception:
                logger.exception("Scheduled rebalance failed for portfolio %s.", portfolio.id)

    def initialize_live_portfolio(self) -> tuple[Portfolio, int, int]:
        """Load persisted portfolios and perform the initial checkpoint catch-up."""
        results = self.sync_saved_portfolios()
        if not results:
            raise RuntimeError("No active comparison portfolios found; run scripts/initialize_live_portfolios.py first.")
        return results[0]

    def sync_saved_portfolios(self) -> list[tuple[Portfolio, int, int]]:
        """Replay newly completed daily sessions for every saved active portfolio."""
        rows = self.repository.get_active_portfolios()
        if not rows:
            raise RuntimeError("No active comparison portfolios found; run scripts/initialize_live_portfolios.py first.")
        from app.trading.services.historical import replay_portfolio
        from zoneinfo import ZoneInfo

        new_york = ZoneInfo("America/New_York")
        results: list[tuple[Portfolio, int, int]] = []
        for row in rows:
            if not row.backtest_complete or row.last_processed_session is None:
                raise RuntimeError("A portfolio has no completed saved checkpoint; run the initializer script first.")
            events = []
            if row.news_enabled:
                checkpoint_close = datetime.combine(
                    row.last_processed_session, time(16, 0), tzinfo=new_york,
                ).astimezone(timezone.utc)
                events = self.repository.get_completed_news_events(
                    row.id, checkpoint_close, datetime.now(timezone.utc), max_per_day=10,
                )
            replay_result = replay_portfolio(self.repository, row, news_events=events)
            row = replay_result[0]
            if self._backfill_daily_trade_metrics(row):
                self.repository.save_portfolio(row)
            results.append(replay_result)
        return results

    def _backfill_daily_trade_metrics(self, portfolio: Portfolio) -> bool:
        """Repair turnover and cost values on stored replay days using their saved fills."""
        from math import isclose

        def session_date(value: datetime):
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return aware.astimezone(NEW_YORK).date()

        orders = self.repository.list_orders(portfolio.id, limit=10_000)
        totals: dict[object, list[float]] = {}
        for order in orders:
            day = session_date(order.created_at)
            row = totals.setdefault(day, [0.0, 0.0])
            row[0] += order.gross_value
            row[1] += order.transaction_cost

        values_by_day = {session_date(point.timestamp): point.total_value for point in portfolio.value_history}
        metric_days = sorted({session_date(metric.date) for metric in portfolio.daily_metrics})
        prior_values: dict[object, float] = {}
        previous_value = portfolio.initial_capital
        for day in metric_days:
            prior_values[day] = previous_value
            previous_value = values_by_day.get(day, previous_value)

        changed = False
        for metric in portfolio.daily_metrics:
            day = session_date(metric.date)
            values = totals.get(day, [0.0, 0.0])
            denominator = prior_values.get(day, 0.0)
            turnover = values[0] / denominator if denominator > 0 else 0.0
            if (not isclose(metric.turnover, turnover, rel_tol=1e-9, abs_tol=1e-12)
                    or not isclose(metric.transaction_cost, values[1], rel_tol=1e-9, abs_tol=1e-8)):
                metric.turnover = max(0.0, turnover)
                metric.transaction_cost = max(0.0, values[1])
                changed = True
        return changed

    def refresh_active_portfolios(self) -> None:
        """Refresh live marks and metrics without changing target positions."""
        for portfolio in self.repository.get_active_portfolios():
            try:
                self._refresh_market_values(portfolio)
            except Exception:
                logger.exception("Could not refresh market values for portfolio %s.", portfolio.id)

    def process_due_rebalances(self) -> int:
        """Fill pending signals at the scheduled session's daily-bar open."""
        self.reconcile_pending_news_rebalances()
        now = datetime.now(timezone.utc)
        pending = self.repository.get_pending_rebalances(due_before=now)
        filled = 0
        for plan in pending:
            portfolio = self.repository.get_portfolio(plan.portfolio_id)
            if portfolio is None or portfolio.status != PortfolioStatus.ACTIVE:
                self.repository.finish_pending_rebalance(plan.id, error="Portfolio is missing or inactive.")
                continue
            tickers = sorted(set(plan.target_weights) | {item.ticker_id for item in portfolio.positions})
            try:
                from zoneinfo import ZoneInfo

                session_date = plan.scheduled_for.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                prices = download_open_prices_on(tickers, session_date)
                event_id = plan.event_ids[0] if plan.event_ids else None
                self._execute_target_weights(
                    portfolio, plan.target_weights, prices, event_id=event_id,
                    event_ids=plan.event_ids, ticker_event_ids=plan.ticker_event_ids,
                    reason=plan.reason, execution_time=plan.scheduled_for,
                )
                self._refresh_positions(portfolio, prices)
                portfolio.last_rebalanced_at = plan.scheduled_for
                portfolio.last_rebalance_trigger = plan.reason
                self._record_daily_metrics(portfolio)
                self.repository.save_portfolio(portfolio)
                self.repository.finish_pending_rebalance(plan.id, executed_at=plan.scheduled_for)
                filled += 1
            except Exception as exc:
                logger.info("Pending rebalance %s awaits its daily open price: %s", plan.id, exc)
                self.repository.finish_pending_rebalance(plan.id, error=str(exc))
        return filled

    def reconcile_pending_news_rebalances(self, *, portfolio_id: str | None = None) -> int:
        """Apply the current impact filter to older pending plans once before display/execution."""
        changed = 0
        portfolios = [p for p in self.repository.get_active_portfolios() if p.news_enabled
                      and (portfolio_id is None or p.id == portfolio_id)]
        for portfolio in portfolios:
            current_weights = {position.ticker_id: position.weight for position in portfolio.positions}
            for plan in self.repository.get_pending_rebalances(portfolio_id=portfolio.id):
                if plan.reason != "news_sentiment" or plan.news_filter_applied:
                    continue
                cache = {}
                candidates: list[tuple[float, str, str]] = []
                for ticker, ids in plan.ticker_event_ids.items():
                    for linked_id in ids:
                        if linked_id not in cache:
                            cache[linked_id] = self.repository.get_news_event(linked_id)
                        event = cache[linked_id]
                        if not event or not event.sentiment:
                            continue
                        impact = event.sentiment.impact_score
                        sentiment = event.sentiment.score
                        if (impact is None or impact < max(MIN_NEWS_IMPACT_SCORE, portfolio.config.min_news_impact_score)
                                or sentiment is None or abs(sentiment) < MIN_NEWS_SENTIMENT_MAGNITUDE):
                            continue
                        relevance = max((item.relevance_score for item in event.relevant_tickers
                                         if item.ticker_id == ticker), default=0.0)
                        if relevance < 0.55:
                            continue
                        signal = float(sentiment) * float(impact) * float(relevance)
                        if abs(signal) >= max(portfolio.config.sentiment_delta_threshold, 0.18):
                            candidates.append((abs(signal), ticker, linked_id))
                ranked = sorted(candidates, reverse=True)
                allowed = {ticker for _, ticker, _ in ranked[:MAX_NEWS_TICKERS_PER_PLAN]}
                filtered_links: dict[str, list[str]] = {}
                for _, ticker, linked_id in ranked:
                    if ticker in allowed:
                        filtered_links.setdefault(ticker, [])
                        if linked_id not in filtered_links[ticker]:
                            filtered_links[ticker].append(linked_id)
                targets = dict(plan.target_weights)
                for ticker in plan.ticker_event_ids:
                    if ticker not in allowed:
                        if current_weights.get(ticker, 0.0) > 0:
                            targets[ticker] = current_weights[ticker]
                        else:
                            targets.pop(ticker, None)
                targets = {ticker: weight for ticker, weight in targets.items() if float(weight) > 0}
                event_ids = list(dict.fromkeys(event_id for ids in filtered_links.values() for event_id in ids))
                if not filtered_links:
                    self.repository.cancel_pending_rebalance(
                        plan.id, reason="Cancelled: no linked news signals met the impact, sentiment, and relevance filters.",
                    )
                else:
                    self.repository.update_pending_news_targets(
                        plan.id, target_weights=targets, event_ids=event_ids, ticker_event_ids=filtered_links,
                    )
                changed += 1
        return changed

    def _active_portfolio(self, portfolio_id: str) -> Portfolio:
        portfolio = self.repository.get_portfolio(portfolio_id)
        if portfolio is None:
            raise LookupError("Portfolio not found.")
        if portfolio.status != PortfolioStatus.ACTIVE:
            raise ValueError("Portfolio is not active.")
        return portfolio

    def _latest_prices(self, tickers: list[str]) -> dict[str, float]:
        requested = list(dict.fromkeys(tickers))
        if not requested:
            return {}
        return download_latest_prices(requested)

    def _execute_target_weights(self, portfolio: Portfolio, targets: dict[str, float], prices: dict[str, float], *,
                                event_id: str | None = None, event_ids: list[str] | None = None,
                                ticker_event_ids: dict[str, list[str]] | None = None,
                                reason: str, execution_time: datetime | None = None) -> None:
        current_shares = {position.ticker_id: position.shares for position in portfolio.positions}
        total_value = portfolio.cash + sum(position.shares * prices.get(position.ticker_id, position.last_price) for position in portfolio.positions)
        ticker_event_ids = ticker_event_ids or {}

        # News signals increase target weights on top of the existing portfolio.
        # Keep the basket fully invested at most; otherwise buys are silently
        # clipped for lack of cash and the plan can be marked filled without orders.
        target_total = sum(max(0.0, float(weight)) for weight in targets.values())
        if reason == "news_sentiment" and target_total > 1.0:
            targets = {ticker: max(0.0, float(weight)) / target_total
                       for ticker, weight in targets.items()}

        desired_shares = {
            ticker: int(max(0.0, weight) * total_value / prices[ticker])
            for ticker, weight in targets.items()
            if ticker in prices and prices[ticker] > 0
        }

        for ticker, shares in current_shares.items():
            desired_shares.setdefault(ticker, 0)
        def order_origin(ticker: str) -> list[str]:
            ids = ticker_event_ids.get(ticker, [])
            if not ids and reason == "news_sentiment":
                return event_ids or ([event_id] if event_id else [])
            return ids

        # Sell first to fund new buys and avoid transient cash shortfalls.
        for ticker, current in current_shares.items():
            sell_quantity = current - desired_shares[ticker]
            if sell_quantity > 0:
                linked_ids = order_origin(ticker)
                order_reason = "news_sentiment" if linked_ids else reason
                self._execute_at_price(
                    portfolio,
                    OrderRequestDTO(ticker_id=ticker, side=OrderSide.SELL, quantity=sell_quantity,
                                    event_id=linked_ids[0] if linked_ids else None, reason=order_reason),
                    prices[ticker],
                    event_ids=linked_ids,
                    created_at=execution_time,
                )
        for ticker, desired in desired_shares.items():
            current = next((position.shares for position in portfolio.positions if position.ticker_id == ticker), 0)
            buy_quantity = desired - current
            if buy_quantity > 0:
                price = prices[ticker]
                affordable = int(portfolio.cash / (price * (1.0 + portfolio.config.transaction_cost)))
                buy_quantity = min(buy_quantity, affordable)
                if buy_quantity:
                    linked_ids = order_origin(ticker)
                    order_reason = "news_sentiment" if linked_ids else reason
                    self._execute_at_price(
                        portfolio,
                        OrderRequestDTO(ticker_id=ticker, side=OrderSide.BUY, quantity=buy_quantity,
                                        event_id=linked_ids[0] if linked_ids else None, reason=order_reason),
                        price,
                        event_ids=linked_ids,
                        created_at=execution_time,
                    )

    def _execute_at_price(self, portfolio: Portfolio, request: OrderRequestDTO, price: float, *,
                          event_ids: list[str] | None = None, created_at: datetime | None = None) -> TradeOrder:
        position = next((item for item in portfolio.positions if item.ticker_id == request.ticker_id), None)
        fee = price * request.quantity * portfolio.config.transaction_cost
        if request.side == OrderSide.BUY:
            cash_required = price * request.quantity + fee
            if cash_required > portfolio.cash:
                raise ValueError("Insufficient portfolio cash for order and transaction cost.")
            old_shares = position.shares if position else 0
            old_cost = position.average_cost if position else 0.0
            new_shares = old_shares + request.quantity
            average_cost = (old_shares * old_cost + request.quantity * price) / new_shares
            if position is None:
                position = PortfolioPosition(ticker_id=request.ticker_id, shares=new_shares, average_cost=average_cost)
                portfolio.positions.append(position)
            else:
                position.shares = new_shares
                position.average_cost = average_cost
            portfolio.cash -= cash_required
        else:
            if position is None or request.quantity > position.shares:
                raise ValueError("Sell quantity exceeds the current position.")
            gross = price * request.quantity
            portfolio.total_realized_pnl += (price - position.average_cost) * request.quantity - fee
            position.shares -= request.quantity
            portfolio.cash += gross - fee
            if position.shares == 0:
                portfolio.positions.remove(position)
        return self.repository.insert_order(
            request,
            portfolio=portfolio,
            price=price,
            transaction_cost=fee,
            quantity=request.quantity,
            event_id=request.event_id,
            event_ids=event_ids,
            created_at=created_at,
        )

    def _refresh_market_values(self, portfolio: Portfolio) -> None:
        prices = self._latest_prices([position.ticker_id for position in portfolio.positions]) if portfolio.positions else {}
        self._refresh_positions(portfolio, prices)
        try:
            benchmark_price = download_latest_prices([portfolio.config.benchmark_ticker]).get(
                portfolio.config.benchmark_ticker
            )
        except Exception:
            logger.exception("Could not refresh benchmark %s; keeping its last good mark.", portfolio.config.benchmark_ticker)
            benchmark_price = None
        if benchmark_price is not None:
            current_benchmark = float(benchmark_price)
            if portfolio.benchmark_initial_price is None:
                portfolio.benchmark_initial_price = current_benchmark
            portfolio.benchmark_value = portfolio.initial_capital * current_benchmark / portfolio.benchmark_initial_price
        self._record_daily_metrics(portfolio)
        self.repository.save_portfolio(portfolio)

    def _refresh_positions(self, portfolio: Portfolio, prices: dict[str, float]) -> None:
        invested = 0.0
        unrealized = 0.0
        for position in portfolio.positions:
            if position.ticker_id in prices:
                position.last_price = prices[position.ticker_id]
            position.market_value = position.shares * position.last_price
            position.unrealized_pnl = (position.last_price - position.average_cost) * position.shares
            position.updated_at = datetime.now(timezone.utc)
            invested += position.market_value
            unrealized += position.unrealized_pnl
        portfolio.portfolio_value = portfolio.cash + invested
        portfolio.total_unrealized_pnl = unrealized
        for position in portfolio.positions:
            position.weight = position.market_value / portfolio.portfolio_value if portfolio.portfolio_value else 0.0

    def _record_daily_metrics(self, portfolio: Portfolio) -> None:
        now = datetime.now(timezone.utc)
        session_date = current_metric_session(now)
        if session_date is None:
            session_date = now.astimezone(NEW_YORK).date()

        def nyse_date(value: datetime):
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return aware.astimezone(NEW_YORK).date()

        def utc_key(value: datetime):
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return aware.astimezone(timezone.utc)

        local_today = now.astimezone(NEW_YORK).date()

        def normalize_session_timestamp(value: datetime) -> datetime:
            """Keep current pre-open marks on the last completed NYSE session.

            Older code selected the prior session for the metric date before
            the open, but persisted the wall-clock timestamp. That made a
            stale pre-market value look like a new trading day's chart point.
            """
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            local = aware.astimezone(NEW_YORK)
            if local.date() == local_today and session_date != local.date():
                return datetime.combine(session_date, time(16, 0), tzinfo=NEW_YORK).astimezone(timezone.utc)
            return aware.astimezone(timezone.utc)

        # Repair snapshots written by older versions too: pre-open marks must
        # remain anchored to the previous completed session in persisted data.
        for item in portfolio.daily_metrics:
            item.date = normalize_session_timestamp(item.date)
        for item in portfolio.value_history:
            item.timestamp = normalize_session_timestamp(item.timestamp)

        snapshot_timestamp = normalize_session_timestamp(now)

        # Older service versions appended multiple snapshots for one NYSE
        # session. Keep the newest mark per session before calculating returns
        # or selecting today's row, otherwise duplicate dates skew chart spacing.
        metrics_by_session = {}
        for item in sorted(portfolio.daily_metrics, key=lambda row: utc_key(row.date)):
            key = nyse_date(item.date)
            previous = metrics_by_session.get(key)
            if previous and not item.position_weights and previous.position_weights:
                item.position_weights = dict(previous.position_weights)
            metrics_by_session[key] = item
        portfolio.daily_metrics = sorted(metrics_by_session.values(), key=lambda row: utc_key(row.date))
        values_by_session = {}
        for item in sorted(portfolio.value_history, key=lambda row: utc_key(row.timestamp)):
            values_by_session[nyse_date(item.timestamp)] = item
        portfolio.value_history = sorted(values_by_session.values(), key=lambda row: utc_key(row.timestamp))

        prior_points = [point for point in portfolio.value_history if nyse_date(point.timestamp) < session_date]
        previous_point = prior_points[-1] if prior_points else None
        previous_value = previous_point.total_value if previous_point else portfolio.initial_capital
        total_value = portfolio.portfolio_value
        daily_pnl = total_value - previous_value
        daily_return = daily_pnl / previous_value if previous_value else 0.0
        returns = [point.total_value for point in prior_points] + [total_value]
        daily_returns = np.diff(returns) / np.maximum(returns[:-1], 1e-12) if len(returns) > 1 else np.array([])
        volatility = float(np.std(daily_returns, ddof=1) * math.sqrt(252)) if len(daily_returns) > 1 else 0.0
        sharpe = float(np.mean(daily_returns) / np.std(daily_returns, ddof=1) * math.sqrt(252)) if len(daily_returns) > 1 and np.std(daily_returns, ddof=1) else 0.0
        drawdown = total_value / max(portfolio.peak_value, total_value, 1e-12) - 1.0
        day_start = datetime.combine(session_date, time.min, tzinfo=NEW_YORK).astimezone(timezone.utc)
        todays_orders = self.repository.list_orders(portfolio.id, limit=10000, since=day_start)
        daily_cost = sum(order.transaction_cost for order in todays_orders)
        daily_turnover = sum(order.gross_value for order in todays_orders) / previous_value if previous_value else 0.0
        metric = PortfolioDailyMetrics(
            date=snapshot_timestamp,
            portfolio_value=total_value,
            position_weights={position.ticker_id: position.weight for position in portfolio.positions if position.shares > 0},
            daily_pnl=daily_pnl,
            daily_return=daily_return,
            cumulative_pnl=total_value - portfolio.initial_capital,
            cumulative_return=total_value / portfolio.initial_capital - 1.0,
            drawdown=min(0.0, drawdown),
            annualized_volatility=volatility,
            sharpe_ratio=sharpe,
            realized_pnl=portfolio.total_realized_pnl,
            unrealized_pnl=portfolio.total_unrealized_pnl,
            benchmark_return=(portfolio.benchmark_value / previous_point.benchmark_value - 1.0)
            if previous_point and previous_point.benchmark_value else None,
            turnover=daily_turnover,
            transaction_cost=daily_cost,
        )
        metric_index = next((index for index in range(len(portfolio.daily_metrics) - 1, -1, -1)
                             if nyse_date(portfolio.daily_metrics[index].date) == session_date), None)
        if metric_index is None:
            portfolio.daily_metrics.append(metric)
        else:
            portfolio.daily_metrics[metric_index] = metric
        portfolio.daily_metrics.sort(key=lambda point: utc_key(point.date))
        portfolio.daily_metrics = portfolio.daily_metrics[-3650:]
        portfolio.peak_value = max(portfolio.peak_value, total_value)
        point_index = next((index for index in range(len(portfolio.value_history) - 1, -1, -1)
                            if nyse_date(portfolio.value_history[index].timestamp) == session_date), None)
        if point_index is None:
            from app.trading.model import PortfolioValuePoint
            portfolio.value_history.append(PortfolioValuePoint(
                timestamp=snapshot_timestamp,
                total_value=total_value,
                cash=portfolio.cash,
                invested_value=total_value - portfolio.cash,
                benchmark_value=portfolio.benchmark_value,
            ))
        else:
            point = portfolio.value_history[point_index]
            point.total_value = total_value
            point.cash = portfolio.cash
            point.invested_value = total_value - portfolio.cash
            point.benchmark_value = portfolio.benchmark_value
            point.timestamp = snapshot_timestamp
        portfolio.value_history.sort(key=lambda point: utc_key(point.timestamp))
        portfolio.value_history = portfolio.value_history[-3650:]
