"""Restore missing recent news-portfolio weights from recorded shares and trades.

Run inside the trading container. By default this is a dry run; pass --apply to
write only missing daily position_weights snapshots after validating market value.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from app.trading.repository import TradingRepository
from app.trading.services.market_data import download_daily_bars

NEW_YORK = ZoneInfo("America/New_York")


def session_date(value: datetime) -> date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(NEW_YORK).date()


def backfill_recent_position_weights(repo: TradingRepository, *, apply: bool = False, portfolio_id: str | None = None, from_date: date = date(2026, 9, 9)) -> int:
    portfolios = repo.list_portfolios()
    portfolio = next((p for p in portfolios if p.id == portfolio_id), None) if portfolio_id else next((p for p in portfolios if p.news_enabled), None)
    if portfolio is None:
        raise ValueError("News-aware portfolio not found")

    missing = [metric for metric in portfolio.daily_metrics if session_date(metric.date) >= from_date and not metric.position_weights]
    if not missing:
        print("No missing weights in the requested date range.")
        return 0

    start_date = min(session_date(metric.date) for metric in missing)
    end_date = max(session_date(metric.date) for metric in portfolio.daily_metrics)
    ticker_ids = sorted({position.ticker_id.upper() for position in portfolio.positions})
    current_shares = {position.ticker_id.upper(): int(position.shares) for position in portfolio.positions}
    order_start = datetime.combine(start_date - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    order_docs = list(repo.orders.find({"portfolio_id": portfolio.id, "created_at": {"$gte": order_start}}).sort("created_at", 1))
    ticker_ids = sorted(set(ticker_ids) | {str(order["ticker_id"]).upper() for order in order_docs})
    bars = download_daily_bars(ticker_ids, start=start_date.isoformat())
    closes = bars["Close"]
    close_by_date: dict[date, dict[str, float]] = defaultdict(dict)
    for index, row in closes.iterrows():
        session = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
        for ticker in ticker_ids:
            if ticker in row and row[ticker] == row[ticker] and float(row[ticker]) > 0:
                close_by_date[session][ticker] = float(row[ticker])

    orders_by_day: dict[date, list[dict]] = defaultdict(list)
    for order in order_docs:
        created = order.get("executed_at") or order.get("created_at")
        if created:
            orders_by_day[session_date(created)].append(order)

    invested_by_day = {session_date(point.timestamp): float(point.invested_value) for point in portfolio.value_history}
    metrics_by_day: dict[date, list] = defaultdict(list)
    for metric in portfolio.daily_metrics:
        metrics_by_day[session_date(metric.date)].append(metric)

    dates = sorted({session_date(metric.date) for metric in missing})
    missing_dates = set(dates)
    rewind_dates = sorted({
        session_date(metric.date)
        for metric in portfolio.daily_metrics
        if start_date <= session_date(metric.date) <= end_date
    } | {
        day for day in orders_by_day if start_date <= day <= end_date
    })
    calculated: dict[date, dict[str, float]] = {}
    checks = []
    for day in reversed(rewind_dates):
        if day in missing_dates:
            prices = close_by_date.get(day, {})
            shares = {}
            missing_prices = []
            for ticker, quantity in current_shares.items():
                if quantity <= 0:
                    continue
                price = prices.get(ticker)
                if price is None:
                    missing_prices.append(ticker)
                else:
                    shares[ticker] = quantity
            expected = invested_by_day.get(day)
            market_value = sum(shares[ticker] * prices[ticker] for ticker in shares)
            error = abs(market_value - expected) / expected if expected else float("inf")
            if missing_prices or not expected or error > 0.025:
                checks.append((day, "SKIP", round(error * 100, 2), len(shares), missing_prices[:4]))
            else:
                total_value = max(metric.portfolio_value for metric in metrics_by_day[day])
                calculated[day] = {ticker: shares[ticker] * prices[ticker] / total_value for ticker in shares if shares[ticker] * prices[ticker] > 0}
                checks.append((day, "READY", round(error * 100, 2), len(calculated[day]), []))

        for order in reversed(orders_by_day.get(day, [])):
            ticker = str(order["ticker_id"]).upper()
            quantity = int(order["quantity"])
            side = str(order["side"]).lower()
            current_shares[ticker] = current_shares.get(ticker, 0) + (quantity if side == "sell" else -quantity)
            if current_shares[ticker] < 0:
                raise RuntimeError(f"Trade history rewound to a negative position in {ticker} on {day}")

    for day, status, error, count, missing_prices in sorted(checks):
        print(f"{day} {status}: {count} holdings; market-value difference {error}%" + (f"; no close for {', '.join(missing_prices)}" if missing_prices else ""))

    ready = set(calculated)
    print(f"Validated {len(ready)}/{len(dates)} dates; mode={'apply' if apply else 'dry-run'}")
    if not apply or not ready:
        return len(ready)

    for day, weights in calculated.items():
        for metric in metrics_by_day[day]:
            if not metric.position_weights:
                repo.portfolios.update_one(
                    {"_id": ObjectId(portfolio.id), "daily_metrics.date": metric.date},
                    {"$set": {"daily_metrics.$[row].position_weights": weights}},
                    array_filters=[{"row.date": metric.date, "row.position_weights": {"$eq": {}}}],
                )
    print(f"Wrote weights for {len(ready)} market dates.")
    return len(ready)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write validated missing weights to MongoDB")
    parser.add_argument("--portfolio-id", help="defaults to the active news-aware portfolio")
    parser.add_argument("--from-date", default="2026-09-09", help="first date to consider, inclusive")
    args = parser.parse_args()

    repo = TradingRepository()
    try:
        backfill_recent_position_weights(repo, apply=args.apply, portfolio_id=args.portfolio_id, from_date=date.fromisoformat(args.from_date))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
