"""Line-delimited TCP interface between the NLP and trading processes."""

from __future__ import annotations

import json
import logging
import socketserver
import threading
import time
from datetime import datetime, time as DayTime
from zoneinfo import ZoneInfo

from app.trading.services.market_data import latest_completed_session

from app.trading.constants import SOCKET_HOST, SOCKET_PORT

logger = logging.getLogger(__name__)
PORTFOLIO_STATE_LOCK = threading.RLock()


class _NewsEventHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(65537)
        if len(raw) > 65536:
            self.wfile.write(b'{"status":"rejected","detail":"message too large"}\n')
            return
        try:
            message: dict[str, object] = json.loads(raw)
            if message.get("type") != "news_scores_updated":
                raise ValueError("unsupported message type")
            event_id = str(message["event_id"])
            raw_tickers = message["ticker_ids"]
            if not isinstance(raw_tickers, list) or not all(isinstance(ticker, str) for ticker in raw_tickers):
                raise ValueError("ticker_ids must be an array of ticker strings")
            ticker_ids = [ticker.upper().replace("-", ".") for ticker in raw_tickers]
            from app.trading.repository import TradingRepository
            from app.trading.services.portfolio_service import PortfolioService

            repository = TradingRepository()
            try:
                with PORTFOLIO_STATE_LOCK:
                    PortfolioService(repository).handle_news_event(event_id, ticker_ids)
            finally:
                repository.close()
            self.wfile.write(b'{"status":"accepted"}\n')
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception("Rejected invalid NLP trading-socket message.")
            self.wfile.write(b'{"status":"rejected"}\n')
        except Exception:
            logger.exception("Trading service failed to process an NLP news event.")
            self.wfile.write(b'{"status":"failed"}\n')


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_socket() -> None:
    with _ThreadingServer((SOCKET_HOST, SOCKET_PORT), _NewsEventHandler) as server:
        logger.info("Trading event socket listening on %s:%d.", SOCKET_HOST, SOCKET_PORT)
        server.serve_forever(poll_interval=1.0)


def run_portfolio_engine() -> None:
    """Restore/backfill portfolios, execute due open orders, and keep marks current."""
    from app.trading.constants import PENDING_REBALANCE_POLL_SECONDS
    from app.trading.services.portfolio_service import PortfolioService

    new_york = ZoneInfo("America/New_York")
    close_after = DayTime(16, 15)
    service = PortfolioService()
    initialized = False
    last_sync_attempt = 0.0
    last_mark = 0.0
    last_strategy_check_session = None
    while True:
        try:
            with PORTFOLIO_STATE_LOCK:
                if not initialized:
                    migration_id = "daily-position-weights-backfill-v1"
                    if not service.repository.migrations.find_one({"_id": migration_id}):
                        logger.info("Backfilling missing historical portfolio weights; this may take a few minutes.")
                        try:
                            from scripts.backfill_position_weights import backfill_missing_position_weights

                            result = backfill_missing_position_weights(service.repository, apply=True)
                            service.repository.migrations.insert_one({
                                "_id": migration_id,
                                "completed_at": datetime.now(ZoneInfo("UTC")),
                                **result,
                            })
                            logger.info("Historical portfolio weights backfill completed: %s", result)
                        except Exception:
                            logger.exception("Historical portfolio weights backfill failed; it will retry on restart.")
                    repair_id = "daily-position-weights-repair-v2"
                    if not service.repository.migrations.find_one({"_id": repair_id}):
                        logger.info("Repairing recent saved weights and duplicate daily chart snapshots.")
                        try:
                            from datetime import timezone
                            def session_day(value):
                                aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                                return aware.astimezone(new_york).date()

                            deduped = 0
                            for saved in service.repository.list_portfolios():
                                metrics = {}
                                for item in sorted(saved.daily_metrics, key=lambda row: row.date):
                                    key = session_day(item.date)
                                    previous = metrics.get(key)
                                    if previous and not item.position_weights and previous.position_weights:
                                        item.position_weights = dict(previous.position_weights)
                                    metrics[key] = item
                                values = {}
                                for item in sorted(saved.value_history, key=lambda row: row.timestamp):
                                    values[session_day(item.timestamp)] = item
                                changed = len(metrics) != len(saved.daily_metrics) or len(values) != len(saved.value_history)
                                deduped += len(saved.daily_metrics) - len(metrics) + len(saved.value_history) - len(values)
                                saved.daily_metrics = sorted(metrics.values(), key=lambda row: row.date)
                                saved.value_history = sorted(values.values(), key=lambda row: row.timestamp)
                                if changed:
                                    service.repository.save_portfolio(saved)

                            from scripts.backfill_recent_position_weights import backfill_recent_position_weights

                            repaired_weights = backfill_recent_position_weights(service.repository, apply=True)
                            unresolved_weights = any(
                                portfolio.news_enabled and not metric.position_weights
                                for portfolio in service.repository.list_portfolios()
                                for metric in portfolio.daily_metrics
                                if session_day(metric.date).isoformat() >= "2026-09-09"
                            )
                            if unresolved_weights:
                                logger.warning("Some recent weight rows did not pass market-value validation; repair will retry after restart.")
                            else:
                                service.repository.migrations.insert_one({
                                    "_id": repair_id,
                                    "completed_at": datetime.now(ZoneInfo("UTC")),
                                    "deduplicated_snapshots": deduped,
                                    "validated_weight_dates": repaired_weights,
                                })
                                logger.info("Portfolio history repair completed: duplicate_snapshots=%s validated_weight_dates=%s", deduped, repaired_weights)
                        except Exception:
                            logger.exception("Portfolio history repair failed; it will retry on restart.")
                    service.process_due_rebalances()
                    portfolio, days, orders = service.initialize_live_portfolio()
                    initialized = True
                    logger.info(
                        "Portfolio ready: id=%s value=%.2f replayed_days=%s simulated_orders=%s",
                        portfolio.id, portfolio.portfolio_value, days, orders,
                    )
                service.process_due_rebalances()
                now_local = datetime.now(new_york)
                active = service.repository.get_active_portfolios()
                latest_session = latest_completed_session(now_local.astimezone(ZoneInfo("UTC")))
                monotonic_now = time.monotonic()
                checkpoint_lagging = bool(latest_session and any(
                    portfolio.last_processed_session is None
                    or portfolio.last_processed_session < latest_session
                    for portfolio in active
                ))
                if (now_local.time() >= close_after and checkpoint_lagging
                        and monotonic_now - last_sync_attempt >= 60):
                    last_sync_attempt = monotonic_now
                    for portfolio, days, orders in service.sync_saved_portfolios():
                        logger.info(
                            "Synchronized portfolio %s through daily bars: days=%s orders=%s value=%.2f",
                            portfolio.id, days, orders, portfolio.portfolio_value,
                        )
                # Strategy triggers use completed daily volume bars. Evaluate
                # once after the NYSE close so the normal (non-news) portfolio
                # can create its next-session plan without relying on a manual
                # API call or on the NLP news socket.
                if (now_local.time() >= close_after and latest_session is not None
                        and last_strategy_check_session != latest_session):
                    service.run_scheduled_rebalances()
                    last_strategy_check_session = latest_session
                if monotonic_now - last_mark >= 900:
                    service.refresh_active_portfolios()
                    last_mark = monotonic_now
        except Exception:
            logger.exception("Live portfolio engine cycle failed; retrying shortly.")
            if not initialized:
                initialized = False
        time.sleep(PENDING_REBALANCE_POLL_SECONDS)
