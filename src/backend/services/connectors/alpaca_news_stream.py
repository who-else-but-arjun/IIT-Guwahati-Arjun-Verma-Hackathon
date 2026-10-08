"""Push-based Alpaca real-time news connector (WebSocket)."""

import json
import logging
import os
import threading
from typing import Mapping

import websocket

from dto.news import NewsEventDTO
from constants import ALPACA_NEWS_STREAM_URL, APCA_API_KEY_ID, APCA_API_SECRET_KEY

from .connector import NewsConnector
from utils.news_utils import build_news_event
from utils.stock_utils import filter_sp100

logger = logging.getLogger(__name__)


class AlpacaNewsStream(NewsConnector):
    provider = "alpaca"

    def normalize(self, payload: Mapping[str, object], context: object | None = None) -> NewsEventDTO:
        """Convert one Alpaca streaming news message to the shared DTO."""
        return build_news_event(
            provider="alpaca",
            article_id=payload.get("id") if isinstance(payload.get("id"), (str, int)) else None,
            headline=str(payload.get("headline") or ""),
            summary=str(payload.get("summary") or ""),
            content=str(payload.get("content") or ""),
            url=str(payload.get("url") or ""),
            source=str(payload.get("source") or "alpaca"),
            author=str(payload.get("author") or ""),
            published_at=payload.get("created_at") if isinstance(payload.get("created_at"), str) else None,
            updated_at=payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
            symbols=payload.get("symbols") if isinstance(payload.get("symbols"), (list, str)) else None,
        )

    def __init__(self, on_article, *, api_key=None, api_secret=None, symbols=None, url=None):
        super().__init__(on_article, symbols=symbols)
        self.api_key = api_key or os.getenv("APCA_API_KEY_ID") or APCA_API_KEY_ID
        self.api_secret = api_secret or os.getenv("APCA_API_SECRET_KEY") or APCA_API_SECRET_KEY
        if not self.api_key or not self.api_secret:
            raise ValueError("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY to use Alpaca news streaming.")
        self.url = url or ALPACA_NEWS_STREAM_URL
        self._stop = threading.Event()
        self._app = None

    def _on_open(self, ws):
        # Alpaca sends connected/authenticated control messages after the
        # handshake. Wait for authenticated in _on_message before subscribing.
        logger.info("Alpaca news WebSocket connected; waiting for authentication acknowledgement.")

    def _on_message(self, ws, message):
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Ignoring a non-JSON message from the Alpaca news stream.")
            return
        rows = payload if isinstance(payload, list) else [payload]
        for item in rows:
            if not isinstance(item, dict):
                continue
            message_type = item.get("T")
            if message_type == "success":
                if item.get("msg") == "authenticated":
                    ws.send(json.dumps({"action": "subscribe", "news": ["*"]}))
                    logger.info("Alpaca authenticated; requested the news subscription.")
                else:
                    logger.info("Alpaca stream status: %s", item.get("msg", "success"))
                continue
            if message_type == "subscription":
                logger.info("Alpaca news subscription acknowledged: %s", item.get("news", []))
                continue
            if message_type == "error":
                logger.error("Alpaca stream error %s: %s", item.get("code", "unknown"), item.get("msg", "unknown error"))
                continue
            if message_type != "n":
                continue
            related = filter_sp100(item.get("symbols", []))
            if not set(related).intersection(self.symbols):
                continue
            article = self.ingest({**item, "symbols": related})
            if article is not None:
                logger.info("Received Alpaca news article for %s.", ",".join(related))

    def run_forever(self, *, reconnect_delay=5):
        """Listen continuously; callback runs as soon as a matching article arrives."""
        while not self._stop.is_set():
            self._app = websocket.WebSocketApp(
                self.url,
                header=[f"APCA-API-KEY-ID: {self.api_key}", f"APCA-API-SECRET-KEY: {self.api_secret}"],
                on_open=self._on_open,
                on_message=self._on_message,
            )
            self._app.run_forever(ping_interval=30, ping_timeout=10)
            if not self._stop.wait(reconnect_delay):
                continue

    def stop(self):
        self._stop.set()
        if self._app:
            self._app.close()
