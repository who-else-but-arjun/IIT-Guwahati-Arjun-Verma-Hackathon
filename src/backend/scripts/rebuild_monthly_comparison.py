"""Safely rebuild and promote the paired 30-day paper portfolio comparison."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pymongo import MongoClient


def _copy_collection(source, target) -> int:
    target.drop()
    rows = list(source.find({}))
    if rows:
        target.insert_many(rows, ordered=False)
    return len(rows)


def _replace_documents(collection, rows: list[dict]) -> None:
    collection.delete_many({})
    if rows:
        collection.insert_many(rows, ordered=False)


def _validate_results(staging) -> tuple[list[dict], list[dict], list[dict]]:
    portfolios = list(staging["trading_portfolios"].find({}).sort("name", 1))
    if len(portfolios) != 2 or {row["name"] for row in portfolios} != {
        "Normal Rebalancing", "News + Normal Rebalancing",
    }:
        raise RuntimeError("Staged replay did not produce the expected two comparison portfolios.")
    orders = list(staging["trading_orders"].find({}))
    pending = list(staging["trading_pending_rebalances"].find({}))
    portfolio_by_id = {str(row["_id"]): row for row in portfolios}
    news_ids = {str(row["_id"]) for row in staging["news_events"].find({}, {"_id": 1})}
    for order in orders:
        if order["portfolio_id"] not in portfolio_by_id:
            raise RuntimeError(f"Order {order['_id']} points to an unsaved portfolio.")
        if order.get("reason") == "news_sentiment":
            event_ids = order.get("event_ids") or []
            if not order.get("event_id") or not event_ids or order["event_id"] not in event_ids:
                raise RuntimeError(f"News order {order['_id']} has incomplete event attribution.")
            if any(event_id not in news_ids for event_id in event_ids):
                raise RuntimeError(f"News order {order['_id']} references a missing news event.")
    for plan in pending:
        portfolio = portfolio_by_id.get(plan["portfolio_id"])
        if portfolio is None:
            raise RuntimeError(f"Pending rebalance {plan['_id']} points to an unsaved portfolio.")
        if (portfolio and portfolio.get("news_enabled") and plan.get("reason") == "news_sentiment"
                and not plan.get("event_ids")):
            raise RuntimeError(f"News rebalance {plan['_id']} has no event attribution.")
        if (portfolio.get("news_enabled") and plan.get("reason") == "news_sentiment"
                and not plan.get("ticker_event_ids")):
            raise RuntimeError(f"News rebalance {plan['_id']} has no per-ticker event attribution.")
        if portfolio.get("news_enabled") and plan.get("reason") == "news_sentiment":
            if any(not ids or any(event_id not in plan.get("event_ids", []) for event_id in ids)
                   for ids in plan["ticker_event_ids"].values()):
                raise RuntimeError(f"News rebalance {plan['_id']} has invalid per-ticker event links.")
            if any(event_id not in news_ids for event_id in plan["event_ids"]):
                raise RuntimeError(f"News rebalance {plan['_id']} references a missing news event.")
    return portfolios, orders, pending


def main() -> None:
    production_name = os.getenv("MONGO_DATABASE", "financial_nlp")
    staging_name = os.getenv("COMPARISON_STAGING_DATABASE", "financial_nlp_comparison_stage")
    if staging_name == production_name:
        raise ValueError("Comparison staging database must be different from the production database.")

    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
    production = client[production_name]
    staging = client[staging_name]
    client.drop_database(staging_name)
    copied_news = _copy_collection(production["news_events"], staging["news_events"])
    copied_tickers = _copy_collection(production["tickers"], staging["tickers"])
    print(f"Staged source data: {copied_news} news events, {copied_tickers} tickers.", flush=True)

    os.environ["MONGO_DATABASE"] = staging_name
    from scripts.initialize_live_portfolios import main as run_initializer

    try:
        run_initializer()
        portfolios, orders, pending = _validate_results(staging)
        new_york = ZoneInfo("America/New_York")
        cutoff_day = datetime.now(new_york).date() - timedelta(days=30)
        summaries = []
        for portfolio in portfolios:
            history = sorted(portfolio.get("value_history", []), key=lambda point: point["timestamp"])
            start_points = [
                point for point in history
                if point["timestamp"].astimezone(new_york).date() <= cutoff_day
            ]
            start_point = start_points[-1] if start_points else None
            start_value = start_point["total_value"] if start_point else portfolio["initial_capital"]
            end_value = portfolio["portfolio_value"]
            portfolio_id = str(portfolio["_id"])
            news_orders = [
                order for order in orders
                if order["portfolio_id"] == portfolio_id and order.get("reason") == "news_sentiment"
            ]
            rebalance_dates = {
                order["created_at"].astimezone(new_york).date().isoformat()
                for order in news_orders
            }
            summaries.append({
                "id": portfolio_id,
                "name": portfolio["name"],
                "checkpoint": start_point["timestamp"].astimezone(new_york).date().isoformat()
                if start_point else cutoff_day.isoformat(),
                "checkpoint_value": round(start_value, 2),
                "last_session": portfolio.get("last_processed_session"),
                "final_value": round(end_value, 2),
                "30_day_pnl": round(end_value - start_value, 2),
                "cumulative_pnl": round(end_value - portfolio["initial_capital"], 2),
                "news_order_rows": len(news_orders),
                "news_execution_dates": len(rebalance_dates),
            })

        # Replace only after the complete staged replay and event-link checks pass.
        collection_names = [
            "news_events", "tickers", "trading_portfolios", "trading_orders",
            "trading_pending_rebalances",
        ]
        promotion_rows = [
            ("news_events", list(staging["news_events"].find({}))),
            ("tickers", list(staging["tickers"].find({}))),
            ("trading_portfolios", portfolios),
            ("trading_orders", orders),
            ("trading_pending_rebalances", pending),
        ]
        client.drop_database(f"{staging_name}_backup")
        backup = client[f"{staging_name}_backup"]
        for collection_name in collection_names:
            _copy_collection(production[collection_name], backup[collection_name])
        try:
            for collection_name, rows in promotion_rows:
                _replace_documents(production[collection_name], rows)
        except Exception:
            for collection_name in collection_names:
                _replace_documents(
                    production[collection_name], list(backup[collection_name].find({})),
                )
            raise
        client.drop_database(f"{staging_name}_backup")

        print("Promoted staged comparison portfolios to the live database.", flush=True)
        for summary in summaries:
            print(summary, flush=True)
        print(f"Promoted order rows: {len(orders)}; pending rebalances: {len(pending)}.", flush=True)
        client.drop_database(staging_name)
    finally:
        client.close()


if __name__ == "__main__":
    main()
