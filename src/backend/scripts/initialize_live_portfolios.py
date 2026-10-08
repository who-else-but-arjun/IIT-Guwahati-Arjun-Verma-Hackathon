"""One-time S&P 100 universe setup and matched portfolio comparison.

Creates a five-year normal-strategy baseline through the one-month cutoff,
duplicates that saved state, then replays the final month as (1) normal strategy
and (2) normal plus historically analyzed news. Runtime services subsequently
load these checkpoints and only process new sessions/events.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId

from app.trading.constants import BACKTEST_NAME, DEFAULT_INITIAL_CAPITAL
from app.trading.model import Portfolio
from app.trading.repository import TradingRepository
from app.trading.services.historical import replay_portfolio
from constants import SP100_COMPANIES
from dto.news import NewsEventDTO
from dto.stock import TickerGraphDTO, TickerNameDTO
from models.documents import NewsEvent
from repository.mongo_repository import MongoRepository
from services.connectors.finnhub_news import FinnhubNewsConnector
from services.models.inference import MODEL_SUITE
from services.models.jev_client import JevClient
from services.workflow.news_processor import NewsProcessingWorkflow
from utils.stock_utils import build_stock_correlation_graph
from services.connectors.yfinance_stocks import YFinanceStocksConnector

logger = logging.getLogger("portfolio-initializer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
NEW_YORK = ZoneInfo("America/New_York")
HISTORY_DAYS = 30
MAX_NEWS_PER_DAY = 10
MAX_HISTORICAL_NEWS_EVENTS = 300


def refresh_universe(news_repository: MongoRepository) -> tuple[int, int, int]:
    for symbol, company in SP100_COMPANIES.items():
        news_repository.ensure_ticker_identity(TickerNameDTO(ticker_id=symbol, company_name=company))
    connector = YFinanceStocksConnector()
    bars = connector.get_history(SP100_COMPANIES.keys(), period="5y", interval="1d")
    available = {bar.ticker_id for bar in bars}
    missing = set(SP100_COMPANIES) - available
    for ticker in sorted(missing):
        bars.extend(connector.get_history([ticker], period="5y", interval="1d"))
    graph = build_stock_correlation_graph(bars, min_observations=252)
    for symbol in SP100_COMPANIES:
        graph.setdefault(symbol, TickerGraphDTO(ticker_name=symbol, correlations={}))
    writes = news_repository.save_correlation_graph(graph)
    return len(bars), len(graph), writes


def fetch_and_analyze_news(news_repository: MongoRepository, cutoff: datetime,
                           through: datetime) -> list[tuple[NewsEventDTO, str]]:
    existing_rows = list(news_repository.news_events.find({
        "metadata.provider": "finnhub",
        "event_timestamp": {"$gt": cutoff, "$lte": through},
    }).sort("event_timestamp", 1))
    existing_ids = {str(row["_id"]) for row in existing_rows}
    articles = [NewsEvent.model_validate(row).to_dto() for row in existing_rows]
    selected = _cap_daily_events(articles)
    if len(selected) < MAX_HISTORICAL_NEWS_EVENTS:
        connector = FinnhubNewsConnector(request_interval=1.2)
        fetched = connector.fetch_company_news(
            SP100_COMPANIES.keys(), start=cutoff.date(), end=through.date(), lookback_days=HISTORY_DAYS,
        )
        combined = {
            str(event.metadata.get("provider_article_id") or event.url or event.headline): event
            for event in [*articles, *fetched]
        }
        articles = sorted(combined.values(), key=lambda event: event.event_datetime)
        selected = _cap_daily_events(articles)
    logger.info("Finnhub history contains %s unique articles; selected %s across capped days (%s/day, %s total max).",
                len(articles), len(selected), MAX_NEWS_PER_DAY, MAX_HISTORICAL_NEWS_EVENTS)

    workflow = NewsProcessingWorkflow(news_repository, model_suite=MODEL_SUITE, jev_client=JevClient())
    analyzed: list[tuple[NewsEventDTO, str]] = []
    for index, event in enumerate(selected, start=1):
        event_id = news_repository.save_news(event)
        if event_id not in existing_ids and not news_repository.is_event_processed(event_id):
            workflow.process(event, event_id, score_time=event.event_datetime, notify_trading=False)
        row = news_repository.news_events.find_one({"_id": ObjectId(event_id)})
        if not row or row.get("metadata", {}).get("analysis_status") != "complete":
            logger.warning("Historical analysis %s/%s remains pending: %s", index, len(selected), event_id)
            continue
        document = NewsEvent.model_validate(row)
        analyzed.append((document.to_dto(), event_id))
        if index % 10 == 0 or index == len(selected):
            logger.info("Analyzed/reused %s/%s capped historical news events.", index, len(selected))
    return analyzed


def _cap_daily_events(articles: list[NewsEventDTO]) -> list[NewsEventDTO]:
    articles.sort(key=lambda event: event.event_datetime)
    daily_counts: defaultdict[object, int] = defaultdict(int)
    selected: list[NewsEventDTO] = []
    for event in articles:
        day = event.event_datetime.astimezone(NEW_YORK).date()
        if daily_counts[day] >= MAX_NEWS_PER_DAY:
            continue
        daily_counts[day] += 1
        selected.append(event)
        if len(selected) >= MAX_HISTORICAL_NEWS_EVENTS:
            break
    return selected


def clone_portfolio(repository: TradingRepository, source: Portfolio, *, name: str, news_enabled: bool) -> Portfolio:
    clone_id = str(ObjectId())
    payload = source.model_dump(mode="python", by_alias=True)
    payload.update({"_id": clone_id, "name": name, "news_enabled": news_enabled,
                    "last_news_event_id": None, "processed_news_event_ids": [],
                    "updated_at": datetime.now(timezone.utc)})
    payload.pop("id", None)
    clone = Portfolio.model_validate(payload)
    if clone.id != clone_id:
        raise RuntimeError("Cloned portfolio ID did not match its persisted MongoDB ID.")
    document = _mongo_safe(clone.model_dump(mode="python", by_alias=True))
    document["_id"] = ObjectId(clone_id)
    repository.portfolios.insert_one(document)

    original_orders = list(repository.orders.find({"portfolio_id": source.id}))
    for order in original_orders:
        order["_id"] = str(ObjectId())
        order["portfolio_id"] = clone_id
    if original_orders:
        repository.orders.insert_many(original_orders, ordered=False)
    for plan in repository.get_pending_rebalances(portfolio_id=source.id):
        repository.queue_rebalance(
            portfolio_id=clone_id,
            event_id=plan.event_ids[-1] if len(plan.event_ids) == 1 else None,
            event_ids=plan.event_ids,
            ticker_event_ids=plan.ticker_event_ids,
            decision_at=plan.decision_at,
            scheduled_for=plan.scheduled_for,
            reason=plan.reason,
            target_weights=plan.target_weights,
        )
    return clone


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


def completed_news_for_simulation(repository: MongoRepository, cutoff: datetime,
                                  through: datetime) -> list[tuple[NewsEventDTO, str]]:
    rows = repository.news_events.find({
        "event_timestamp": {"$gt": cutoff, "$lte": through},
        "metadata.analysis_status": "complete",
    }).sort("event_timestamp", 1)
    daily_counts: defaultdict[object, int] = defaultdict(int)
    selected: list[tuple[NewsEventDTO, str]] = []
    for row in rows:
        day = row["event_timestamp"].astimezone(NEW_YORK).date()
        if daily_counts[day] >= MAX_NEWS_PER_DAY:
            continue
        daily_counts[day] += 1
        document = NewsEvent.model_validate(row)
        selected.append((document.to_dto(), str(row["_id"])))
        if len(selected) >= MAX_HISTORICAL_NEWS_EVENTS:
            break
    return selected


def main() -> None:
    initial_capital = float(os.getenv("INITIAL_PORTFOLIO_CAPITAL", str(DEFAULT_INITIAL_CAPITAL)))
    news_repository = MongoRepository()
    trading_repository = TradingRepository()
    try:
        expected_universe_size = len(SP100_COMPANIES)
        graph_rows = news_repository.tickers.count_documents({"ticker_graph": {"$exists": True, "$ne": None}})
        if graph_rows >= expected_universe_size:
            logger.info("S&P100 identities and correlation graph already exist (%s graph nodes).", graph_rows)
        else:
            bars, nodes, edges_written = refresh_universe(news_repository)
            logger.info("S&P100 ready: bars=%s graph_nodes=%s graph_records=%s", bars, nodes, edges_written)

        now_local = datetime.now(NEW_YORK)
        cutoff_day = now_local.date() - timedelta(days=HISTORY_DAYS)
        cutoff = datetime.combine(cutoff_day, datetime.max.time(), tzinfo=NEW_YORK).astimezone(timezone.utc)
        through = now_local.astimezone(timezone.utc)

        existing = trading_repository.list_portfolios()
        normal = next((row for row in existing if row.name == "Normal Rebalancing"), None)
        news_portfolio = next((row for row in existing if row.name == "News + Normal Rebalancing"), None)
        unexpected = [row.name for row in existing if row not in (normal, news_portfolio)]
        if unexpected:
            raise RuntimeError(f"Unexpected existing portfolios prevent comparison setup: {unexpected}")
        if normal is None:
            if news_portfolio is not None:
                raise RuntimeError("Found a news portfolio without its normal baseline; repair that pair before continuing.")
            seed = trading_repository.create_portfolio(name=BACKTEST_NAME, initial_capital=initial_capital)
            seed.name = "Normal Rebalancing"
            seed.news_enabled = False
        else:
            seed = normal
        _, seeded_days, seeded_orders = replay_portfolio(trading_repository, seed, until_date=cutoff_day)
        checkpoint = seed.last_processed_session
        if checkpoint is None:
            raise RuntimeError("Five-year backtest did not save a portfolio checkpoint.")
        if news_portfolio is None:
            news_portfolio = clone_portfolio(
                trading_repository, seed, name="News + Normal Rebalancing", news_enabled=True,
            )
        logger.info("Shared comparison checkpoint: %s; value=%.2f", checkpoint, seed.portfolio_value)

        analyzed = fetch_and_analyze_news(news_repository, cutoff, through)
        simulation_news = completed_news_for_simulation(news_repository, cutoff, through)
        logger.info("News pipeline produced %s completed events for the one-month simulation.", len(simulation_news))

        _, baseline_days, baseline_orders = replay_portfolio(trading_repository, seed)
        _, news_days, news_orders = replay_portfolio(
            trading_repository, news_portfolio, news_events=simulation_news,
        )
        logger.info("Portfolio setup complete: backtest5y_days=%s backtest5y_orders=%s; "
                    "baseline_1m_days=%s orders=%s; news_1m_days=%s orders=%s; "
                    "analyzed_news=%s; baseline_id=%s; news_id=%s",
                    seeded_days, seeded_orders, baseline_days, baseline_orders,
                    news_days, news_orders, len(analyzed), seed.id, news_portfolio.id)
    finally:
        trading_repository.close()
        news_repository.close()


if __name__ == "__main__":
    main()
