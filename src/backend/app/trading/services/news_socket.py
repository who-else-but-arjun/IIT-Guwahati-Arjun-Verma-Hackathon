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
    while True:
        try:
            with PORTFOLIO_STATE_LOCK:
                if not initialized:
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
                        and monotonic_now - last_sync_attempt >= 900):
                    last_sync_attempt = monotonic_now
                    for portfolio, days, orders in service.sync_saved_portfolios():
                        logger.info(
                            "Synchronized portfolio %s through daily bars: days=%s orders=%s value=%.2f",
                            portfolio.id, days, orders, portfolio.portfolio_value,
                        )
                if monotonic_now - last_mark >= 900:
                    service.refresh_active_portfolios()
                    last_mark = monotonic_now
        except Exception:
            logger.exception("Live portfolio engine cycle failed; retrying shortly.")
            if not initialized:
                initialized = False
        time.sleep(PENDING_REBALANCE_POLL_SECONDS)
