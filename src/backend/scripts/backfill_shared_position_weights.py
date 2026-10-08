"""Copy validated pre-news weights to the news-aware portfolio.

The two seeded strategies share the same holdings until the first material
portfolio-value divergence. This fills missing news-aware snapshots only for
dates before that point where the saved values agree within 0.1%.
"""

from __future__ import annotations

from app.trading.repository import TradingRepository

VALUE_TOLERANCE = 0.001


def main() -> None:
    repository = TradingRepository()
    try:
        portfolios = repository.list_portfolios()
        normal = next((portfolio for portfolio in portfolios if not portfolio.news_enabled), None)
        news = next((portfolio for portfolio in portfolios if portfolio.news_enabled), None)
        if normal is None or news is None:
            print("Both normal and news-aware portfolios are required; no snapshots changed.")
            return

        normal_by_day = {metric.date.date(): metric for metric in normal.daily_metrics}
        news_by_day = {metric.date.date(): metric for metric in news.daily_metrics}
        common_days = sorted(normal_by_day.keys() & news_by_day.keys())
        divergence = next((day for day in common_days if
                           abs(normal_by_day[day].portfolio_value - news_by_day[day].portfolio_value)
                           / max(normal_by_day[day].portfolio_value, 1.0) > VALUE_TOLERANCE), None)
        cutoff = divergence or (common_days[-1] if common_days else None)
        if cutoff is None:
            print("No shared daily metrics; no snapshots changed.")
            return

        copied = 0
        for metric in news.daily_metrics:
            day = metric.date.date()
            source = normal_by_day.get(day)
            if day >= cutoff or metric.position_weights or source is None or not source.position_weights:
                continue
            difference = abs(source.portfolio_value - metric.portfolio_value) / max(metric.portfolio_value, 1.0)
            if difference <= VALUE_TOLERANCE:
                metric.position_weights = dict(source.position_weights)
                copied += 1
        if copied:
            repository.save_portfolio(news)
        print(f"Copied {copied} pre-divergence weight snapshots through {cutoff}.")
    finally:
        repository.client.close()


if __name__ == "__main__":
    main()
