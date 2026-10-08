"""Real-time Bluesky posts via the public Jetstream JSON WebSocket."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import urlencode

import websocket

from constants import BLUESKY_JETSTREAM_URL
from dto.news import NewsEventDTO
from .connector import NewsConnector
from utils.news_utils import build_news_event
from utils.bluesky_utils import extract_sp100_symbols, headline_from_post

logger = logging.getLogger(__name__)

class BlueskyNewsStream(NewsConnector):
    """Listen to public post events and emit posts mentioning S&P 100 names."""

    def __init__(self, on_article, *, symbols=None, url: str | None = None):
        super().__init__(on_article, symbols=symbols)
        self.base_url = url or os.getenv("BLUESKY_JETSTREAM_URL", BLUESKY_JETSTREAM_URL)
        self._stop = threading.Event()
        self._app: websocket.WebSocketApp | None = None
        self._rate_lock = threading.Lock()
        self._accepted_posts: deque[float] = deque()
        self._accepted_by_author: dict[str, deque[float]] = defaultdict(deque)
        self._max_posts_per_hour = max(1, int(os.getenv("BLUESKY_MAX_POSTS_PER_HOUR", "12")))
        self._max_posts_per_author_hour = max(1, int(os.getenv("BLUESKY_MAX_POSTS_PER_AUTHOR_PER_HOUR", "2")))

    def _within_rate_limit(self, author: str) -> bool:
        now = time.monotonic()
        cutoff = now - 3600
        with self._rate_lock:
            while self._accepted_posts and self._accepted_posts[0] <= cutoff:
                self._accepted_posts.popleft()
            author_posts = self._accepted_by_author[author]
            while author_posts and author_posts[0] <= cutoff:
                author_posts.popleft()
            if (len(self._accepted_posts) >= self._max_posts_per_hour
                    or len(author_posts) >= self._max_posts_per_author_hour):
                return False
            self._accepted_posts.append(now)
            author_posts.append(now)
            return True

    def normalize(self, event: Mapping[str, object], context: object | None = None) -> NewsEventDTO | None:
        """Map a Jetstream v1 commit event into the shared NewsEvent DTO."""
        commit = event.get("commit")
        if not isinstance(commit, Mapping):
            return None
        if commit.get("collection") != "app.bsky.feed.post" or commit.get("operation") != "create":
            return None
        record = commit.get("record")
        did = event.get("did")
        rkey = commit.get("rkey")
        if not isinstance(record, Mapping) or not isinstance(did, str) or not isinstance(rkey, str):
            return None
        post_text = record.get("text")
        if not isinstance(post_text, str) or not post_text.strip():
            return None
        # Always apply the same strict relevance rules to stream posts; caller
        # context is only a hint and must not bypass the financial-content gate.
        related = extract_sp100_symbols(post_text)
        if not related:
            return None
        if not self._within_rate_limit(did):
            return None

        at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
        post_url = f"https://bsky.app/profile/{did}/post/{rkey}"
        event_time = record.get("createdAt")
        if not isinstance(event_time, str):
            time_us = event.get("time_us")
            event_time = datetime.fromtimestamp(float(time_us) / 1_000_000, tz=timezone.utc) if isinstance(time_us, (int, float)) else None
        article = build_news_event(
            provider="bluesky",
            article_id=at_uri,
            headline=headline_from_post(post_text),
            content=post_text.strip(),
            url=post_url,
            source="Bluesky",
            author=did,
            published_at=event_time,
            text_kind="social_post",
            symbols=related,
        )
        metadata = {
            **article.metadata,
            "author_did": did,
            "post_uri": at_uri,
            "post_cid": str(commit.get("cid") or ""),
            "text_kind": "social_post",
        }
        return article.model_copy(update={"metadata": metadata})

    def _on_open(self, _ws):
        logger.info("Connected to Bluesky Jetstream for S&P 100 related posts.")

    def _on_message(self, _ws, message: str):
        try:
            event = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Ignoring a malformed Bluesky Jetstream event.")
            return
        if not isinstance(event, dict):
            return
        post = self.ingest(event)
        if post is None:
            return
        logger.info("Received Bluesky post for %s.", ",".join(t.ticker_id for t in post.relevant_tickers))

    def _on_error(self, _ws, error):
        logger.warning("Bluesky Jetstream WebSocket error: %s", error)

    def run_forever(self, *, reconnect_delay: int = 5):
        """Keep the public Jetstream connection open and reconnect on disconnect."""
        query = urlencode({"wantedCollections": "app.bsky.feed.post"})
        stream_url = f"{self.base_url}?{query}"
        while not self._stop.is_set():
            self._app = websocket.WebSocketApp(
                stream_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
            )
            self._app.run_forever(ping_interval=30, ping_timeout=10)
            if not self._stop.wait(reconnect_delay):
                logger.info("Reconnecting to Bluesky Jetstream.")

    def stop(self):
        self._stop.set()
        if self._app:
            self._app.close()
