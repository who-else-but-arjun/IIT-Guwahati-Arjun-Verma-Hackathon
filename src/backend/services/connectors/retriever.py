"""Small CLI/demo entry point for S&P 100 source connectors."""

import argparse
import json
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .alpaca_news_stream import AlpacaNewsStream
from .bluesky_news_stream import BlueskyNewsStream
from .finnhub_news import FinnhubNewsConnector
from repository.mongo_repository import MongoRepository
from dto.stock import TickerNameDTO
from constants import SP100_COMPANIES
from utils.stock_utils import build_stock_correlation_graph
from .yfinance_stocks import YFinanceStocksConnector
from services.workflow import NewsProcessingWorkflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sp100-retriever")
ANALYSIS_RETRY_INTERVAL_SECONDS = 5
NEWS_QUEUE_HIGH_WATERMARK = max(25, int(os.getenv("NEWS_QUEUE_HIGH_WATERMARK", "250")))
MAX_NEWS_PER_POLL = max(1, int(os.getenv("MAX_NEWS_PER_POLL", "50")))


def _analysis_worker(repository):
    """Create a local executor and durable Mongo-backed enqueue callback."""
    workflow = NewsProcessingWorkflow(repository)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-analysis")

    def enqueue(article):
        event_id = repository.save_news_if_queue_below(article, max_pending=NEWS_QUEUE_HIGH_WATERMARK)
        if event_id is None:
            logger.info("Live-news intake paused at %s queued stories; skipped provider event.",
                        repository.pending_news_count())
        return event_id

    return workflow, executor, enqueue


def _retry_pending_loop(repository, workflow, executor, stop,
                        interval_seconds=ANALYSIS_RETRY_INTERVAL_SECONDS):
    """Drain all currently due stories; pause briefly only when none are due."""
    while not stop.is_set():
        try:
            processed = executor.submit(workflow.retry_pending, 1).result()
            if processed:
                continue
            stop.wait(interval_seconds)
        except RuntimeError:
            return
        except Exception:
            logger.exception("News analysis worker iteration failed; retrying shortly.")
            stop.wait(interval_seconds)


def _analysis_worker_enabled() -> bool:
    return os.getenv("NEWS_ANALYSIS_WORKER", "true").strip().lower() not in {"0", "false", "no", "off"}


def main():
    parser = argparse.ArgumentParser(description="Retrieve S&P 100 stock prices and news")
    subs = parser.add_subparsers(dest="command", required=True)
    news = subs.add_parser("news", help="Fetch company-news backfill through Finnhub")
    news.add_argument("--symbols", nargs="*", default=["AAPL", "MSFT"])
    news.add_argument("--days", type=int, default=1)
    prices = subs.add_parser("prices", help="Download price history through yfinance")
    prices.add_argument("--symbols", nargs="*", default=["AAPL", "MSFT"])
    prices.add_argument("--period", default="5d")
    prices.add_argument("--interval", default="1d")
    stream = subs.add_parser("listen", help="Stream matching Alpaca news as event callbacks")
    stream.add_argument("--symbols", nargs="*", default=list(SP100_COMPANIES))
    bluesky = subs.add_parser("bluesky", help="Stream S&P 100 related posts from Bluesky Jetstream")
    bluesky.add_argument("--symbols", nargs="*", default=list(SP100_COMPANIES))
    poller = subs.add_parser("poll-news", help="Poll Finnhub for S&P 100 news on an interval")
    poller.add_argument("--interval-seconds", type=int, default=900)
    poller.add_argument("--lookback-days", type=int, default=1)
    analysis = subs.add_parser("analyze", help="Continuously drain the persisted news-analysis queue")
    analysis.add_argument("--idle-seconds", type=int, default=3)
    subs.add_parser("seed-tickers", help="Ensure every S&P 100 ticker has a MongoDB document")
    args = parser.parse_args()

    if args.command == "news":
        rows = FinnhubNewsConnector().fetch_company_news(args.symbols, lookback_days=args.days)
        store = MongoRepository()
        workflow, executor, enqueue = _analysis_worker(store)
        try:
            for row in rows:
                enqueue(row)
            logger.info("Upserted and queued %s news records for analysis", len(rows))
        finally:
            executor.shutdown(wait=True)
            store.close()
        print(json.dumps([row.model_dump(mode="json") for row in rows], indent=2))
    elif args.command == "prices":
        rows = YFinanceStocksConnector().get_history(args.symbols, period=args.period, interval=args.interval)
        store = MongoRepository()
        graph = build_stock_correlation_graph(rows)
        graph_count = store.save_correlation_graph(graph)
        store.close()
        logger.info("Retrieved %s price bars on demand and saved %s ticker graphs into MongoDB", len(rows), graph_count)
        print(json.dumps([row.model_dump(mode="json") for row in rows], indent=2))
    elif args.command == "seed-tickers":
        store = MongoRepository()
        saved = 0
        for symbol, company_name in SP100_COMPANIES.items():
            store.ensure_ticker_identity(TickerNameDTO(
                ticker_id=symbol,
                company_name=company_name,
            ))
            saved += 1
        store.close()
        logger.info("Ensured %s S&P 100 ticker documents in MongoDB", saved)
        print(f"Ensured {saved} S&P 100 ticker documents in MongoDB.")
    elif args.command == "poll-news":
        if args.interval_seconds < 60:
            parser.error("--interval-seconds must be at least 60 to respect Finnhub request limits")
        if args.lookback_days < 1:
            parser.error("--lookback-days must be at least 1")
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        connector = FinnhubNewsConnector()
        store = MongoRepository()
        workflow, executor, enqueue = _analysis_worker(store)
        retry_thread = None
        if _analysis_worker_enabled():
            retry_thread = threading.Thread(
                target=_retry_pending_loop,
                args=(store, workflow, executor, stop),
                daemon=True,
                name="pending-news-analysis-retry",
            )
            retry_thread.start()
        try:
            while not stop.is_set():
                cycle_started = time.monotonic()
                try:
                    pending_count = store.pending_news_count()
                    if pending_count >= NEWS_QUEUE_HIGH_WATERMARK:
                        logger.info("Finnhub intake paused: %d queued stories reached the %d-story high-water mark.",
                                    pending_count, NEWS_QUEUE_HIGH_WATERMARK)
                    else:
                        rows = connector.fetch_company_news(
                            SP100_COMPANIES.keys(), lookback_days=args.lookback_days
                        )
                        event_ids = store.save_news_batch_bounded(
                            rows, max_pending=NEWS_QUEUE_HIGH_WATERMARK,
                            max_new=MAX_NEWS_PER_POLL,
                        )
                        logger.info(
                            "Finnhub poll complete: fetched %d deduplicated articles, persisted %d new stories, queue=%d/%d.",
                            len(rows), len(event_ids), store.pending_news_count(), NEWS_QUEUE_HIGH_WATERMARK,
                        )
                except Exception:
                    logger.exception("Finnhub poll failed; will retry after %d seconds.", args.interval_seconds)
                wait_seconds = max(0.0, args.interval_seconds - (time.monotonic() - cycle_started))
                logger.info("Next Finnhub poll starts in %.0f seconds.", wait_seconds)
                stop.wait(wait_seconds)
        finally:
            if retry_thread:
                retry_thread.join(timeout=2)
            executor.shutdown(wait=False, cancel_futures=True)
            store.close()
    elif args.command in {"listen", "bluesky"}:
        store = MongoRepository()
        workflow, executor, enqueue = _analysis_worker(store)
        retry_stop = threading.Event()
        retry_thread = None
        if _analysis_worker_enabled():
            retry_thread = threading.Thread(
                target=_retry_pending_loop,
                args=(store, workflow, executor, retry_stop),
                daemon=True,
                name="pending-news-analysis-retry",
            )
            retry_thread.start()
        def save_article(article):
            event_id = enqueue(article)
            if event_id is None:
                return
            logger.info(
                "NEW_ARTICLE event_id=%s provider_id=%s source_tickers=%s headline=%s analysis=queued",
                event_id,
                article.metadata.get("provider_article_id"),
                ",".join(item.ticker_id for item in article.relevant_tickers),
                article.headline,
            )
        def bluesky_finance_filter(article):
            # Share the model suite through its single analysis executor so
            # streaming Laya calls cannot race queued sentiment inference.
            try:
                return executor.submit(
                    workflow.models.is_financial_news, article.headline, article.text,
                ).result()
            except Exception:
                logger.exception("FLANG-Laya could not classify Bluesky post; dropping it before persistence.")
                return False
        stream = (
            AlpacaNewsStream(save_article, symbols=args.symbols)
            if args.command == "listen"
            else BlueskyNewsStream(save_article, symbols=args.symbols,
                                   finance_filter=bluesky_finance_filter)
        )
        signal.signal(signal.SIGINT, lambda *_: stream.stop())
        signal.signal(signal.SIGTERM, lambda *_: stream.stop())
        try:
            stream.run_forever()
        finally:
            retry_stop.set()
            if retry_thread:
                retry_thread.join(timeout=2)
            executor.shutdown(wait=False, cancel_futures=True)
            store.close()
    elif args.command == "analyze":
        if args.idle_seconds < 1:
            parser.error("--idle-seconds must be at least 1")
        store = MongoRepository()
        workflow = NewsProcessingWorkflow(store)
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        logger.info("News analysis worker started; draining due events continuously.")
        try:
            while not stop.is_set():
                processed = workflow.retry_pending(limit=1)
                if processed:
                    continue
                stop.wait(args.idle_seconds)
        finally:
            store.close()
    else:
        parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
