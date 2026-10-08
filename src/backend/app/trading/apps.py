"""Trading app startup hooks."""

import logging
import os
import sys
import threading
from pathlib import Path

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class TradingConfig(AppConfig):
    name = "app.trading"
    verbose_name = "Paper Trading"

    def ready(self) -> None:
        args = [Path(arg).name.lower() for arg in sys.argv]
        is_runserver = "runserver" in args
        is_reloader_parent = is_runserver and "--noreload" not in sys.argv and os.getenv("RUN_MAIN") != "true"
        is_wsgi_server = any(name in " ".join(args) for name in ("gunicorn", "uvicorn", "daphne", "hypercorn"))
        if is_reloader_parent or not (is_runserver or is_wsgi_server):
            return
        from app.trading.services.news_socket import run_portfolio_engine, serve_socket

        threading.Thread(target=serve_socket, daemon=True, name="nlp-trading-socket").start()
        threading.Thread(target=run_portfolio_engine, daemon=True, name="live-portfolio-engine").start()
        logger.info("Started the NLP-to-trading event socket.")
