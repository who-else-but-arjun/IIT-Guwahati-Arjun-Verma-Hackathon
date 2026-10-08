"""Restore missing daily position weights by replaying portfolio history.

Run inside the trading service with ``python -m scripts.backfill_position_weights``
to preview, or add ``--apply`` to persist weights for daily metrics with empty
``position_weights``. Existing snapshots are preserved.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.trading.repository import TradingRepository
from app.trading.services.historical import replay_portfolio
from models.documents import NewsEvent

NEW_YORK = ZoneInfo("America/New_York")
VALUE_TOLERANCE = 0.02


class ReplayRepository:
    """Allow historical replay to read data without writing orders or plans."""

    def __init__(self, source: TradingRepository) -> None:
        self.source = source

    def get_pending_rebalances(self, *, portfolio_id: str):
        return []

    def get_ticker_graph(self, ticker_id: str):
        return self.source.get_ticker_graph(ticker_id)

    def finish_pending_rebalance(self, *args, **kwargs) -> None:
        return None

    def queue_rebalance(self, *args, **kwargs) -> None:
        return None

    def insert_orders(self, orders) -> None:
        return None

    def save_portfolio(self, portfolio) -> None:
        return None


def clean_replay_copy(portfolio):
    return portfolio.model_copy(update={
        "cash": portfolio.initial_capital,
        "portfolio_value": portfolio.initial_capital,
        "peak_value": portfolio.initial_capital,
        "benchmark_initial_price": None,
        "benchmark_value": None,
        "total_realized_pnl": 0.0,
        "total_unrealized_pnl": 0.0,
        "positions": [],
        "daily_metrics": [],
        "value_history": [],
        "last_rebalanced_at": None,
        "last_rebalance_trigger": None,
        "last_news_event_id": None,
        "processed_news_event_ids": [],
        "order_count": 0,
        "last_processed_session": None,
        "backtest_complete": False,
    })


def replay_news_events(repository: TradingRepository, start: date, through: date):
    after = datetime.combine(start - timedelta(days=1), time.min, tzinfo=timezone.utc)
    end = datetime.combine(through + timedelta(days=1), time.min, tzinfo=timezone.utc)
    query = {
        "event_timestamp": {"$gt": after, "$lt": end},
        "metadata.analysis_status": "complete",
    }
    per_day: dict[date, int] = defaultdict(int)
    events = []
    for row in repository.news_events.find(query).sort("event_timestamp", 1):
        event = NewsEvent.model_validate(row).to_dto()
        if event.sentiment is None:
            continue
        day = event.event_datetime.astimezone(NEW_YORK).date()
        if per_day[day] >= 10:
            continue
        per_day[day] += 1
        events.append((event, str(row["_id"])))
    return events


def last_metrics_by_date(metrics):
    return {item.date.date(): item for item in metrics}


def backfill_shared_weights(repository) -> int:
    """Copy matching normal weights before the news strategy diverges."""
    portfolios = repository.list_portfolios()
    normal = next((portfolio for portfolio in portfolios if not portfolio.news_enabled), None)
    news = next((portfolio for portfolio in portfolios if portfolio.news_enabled), None)
    if normal is None or news is None:
        return 0
    normal_by_day = last_metrics_by_date(normal.daily_metrics)
    news_by_day = last_metrics_by_date(news.daily_metrics)
    common_days = sorted(normal_by_day.keys() & news_by_day.keys())
    divergence = next((day for day in common_days if
                       abs(normal_by_day[day].portfolio_value - news_by_day[day].portfolio_value)
                       / max(normal_by_day[day].portfolio_value, 1.0) > 0.001), None)
    cutoff = divergence or (common_days[-1] if common_days else None)
    if cutoff is None:
        return 0
    copied = 0
    for metric in news.daily_metrics:
        day = metric.date.date()
        source = normal_by_day.get(day)
        if day >= cutoff or metric.position_weights or source is None or not source.position_weights:
            continue
        difference = abs(source.portfolio_value - metric.portfolio_value) / max(metric.portfolio_value, 1.0)
        if difference <= 0.001:
            metric.position_weights = dict(source.position_weights)
            copied += 1
    if copied:
        repository.save_portfolio(news)
        print(f"Copied {copied} validated pre-divergence snapshots to the news-aware portfolio.")
    return copied


def backfill_missing_position_weights(repository, *, apply: bool = True) -> dict[str, int]:
    shared = backfill_shared_weights(repository) if apply else 0
    safe_total = 0
    replay_repository = ReplayRepository(repository)
    for original in repository.list_portfolios():
        if not original.daily_metrics:
            print(f"{original.name}: no daily metrics; skipped")
            continue
        end_date = max(item.date.date() for item in original.daily_metrics)
        start_date = min(item.date.date() for item in original.daily_metrics)
        clone = clean_replay_copy(original)
        events = replay_news_events(repository, start_date, end_date) if original.news_enabled else []
        replayed, days, _ = replay_portfolio(
            replay_repository,
            clone,
            until_date=end_date,
            news_events=events,
        )
        replay_by_date = last_metrics_by_date(replayed.daily_metrics)
        original_by_date = last_metrics_by_date(original.daily_metrics)
        known = [
            (day, metric, replay_by_date.get(day))
            for day, metric in original_by_date.items()
            if metric.position_weights and replay_by_date.get(day)
        ]
        differences = [
            abs(metric.portfolio_value - simulated.portfolio_value) / max(metric.portfolio_value, 1.0)
            for _, metric, simulated in known
        ]
        max_difference = max(differences, default=0.0)
        within_tolerance = sum(value <= VALUE_TOLERANCE for value in differences)
        updates = []
        skipped = 0
        for day, metric in original_by_date.items():
            simulated = replay_by_date.get(day)
            if metric.position_weights or simulated is None or not simulated.position_weights:
                continue
            difference = abs(metric.portfolio_value - simulated.portfolio_value) / max(metric.portfolio_value, 1.0)
            if difference > VALUE_TOLERANCE:
                skipped += 1
                continue
            updates.append((day, dict(simulated.position_weights)))

        safe_total += len(updates)
        print(
            f"{original.name}: replayed {days} sessions; existing weighted dates {len(known)}; "
            f"within 2% value match {within_tolerance}/{len(known)}; max mismatch {max_difference:.3%}; "
            f"safe backfills {len(updates)}; skipped {skipped}"
        )
        if not apply:
            continue
        by_date = dict(updates)
        changed = False
        for metric in original.daily_metrics:
            weights = by_date.get(metric.date.date())
            if weights is not None and not metric.position_weights:
                metric.position_weights = weights
                changed = True
        if changed:
            repository.save_portfolio(original)
            print(f"  Persisted weights to {len(updates)} daily snapshots.")
    return {"shared_snapshots": shared, "replayed_snapshots": safe_total}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist replayed weights to MongoDB")
    args = parser.parse_args()
    repository = TradingRepository()
    try:
        backfill_missing_position_weights(repository, apply=args.apply)
    finally:
        repository.client.close()


if __name__ == "__main__":
    main()
