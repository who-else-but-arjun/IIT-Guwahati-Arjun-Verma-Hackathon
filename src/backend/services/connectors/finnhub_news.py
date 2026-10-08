"""Finnhub Company News REST connector for backfill and reconciliation."""

import os
import time
from datetime import timedelta
from typing import Mapping

import requests
import logging

from dto.news import NewsEventDTO
from constants import FINNHUB_API_KEY, FINNHUB_COMPANY_NEWS_URL

from .connector import NewsConnector
from utils.news_utils import build_news_event
from utils.stock_utils import filter_sp100
from utils.datetime_utils import parse_date

logger = logging.getLogger(__name__)


class FinnhubNewsConnector(NewsConnector):
    provider = "finnhub"

    def normalize(self, payload: Mapping[str, object], context: object | None = None) -> NewsEventDTO:
        """Convert one Finnhub Company News item to the shared DTO."""
        timestamp = payload.get("datetime")
        if not isinstance(timestamp, (int, float)):
            timestamp = None
        related = payload.get("related")
        related_symbols = related.replace(",", " ").split() if isinstance(related, str) else []
        article_id = payload.get("id")
        return build_news_event(
            provider="finnhub",
            article_id=article_id if isinstance(article_id, (str, int)) else None,
            headline=str(payload.get("headline") or ""),
            summary=str(payload.get("summary") or ""),
            url=str(payload.get("url") or ""),
            source=str(payload.get("source") or "finnhub"),
            published_at=timestamp,
            symbols=[*related_symbols, str(context or "")],
        )

    def __init__(self, api_key=None, session=None, timeout=20, request_interval=1.2, on_article=None, symbols=None):
        super().__init__(on_article, symbols=symbols)
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY") or FINNHUB_API_KEY
        if not self.api_key:
            raise ValueError("Set FINNHUB_API_KEY to use the Finnhub news connector.")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.request_interval = max(0.0, float(request_interval))
        self._last_request_at = 0.0

    def fetch_company_news(self, symbols, *, start=None, end=None, lookback_days=1):
        """Fetch related articles for S&P 100 names and deduplicate across symbols."""
        tickers = filter_sp100(symbols)
        if not tickers:
            return []
        end_date = parse_date(end)
        start_date = parse_date(start) if start is not None else end_date - timedelta(days=lookback_days)
        deduped = {}
        for ticker in tickers:
            delay = self.request_interval - (time.monotonic() - self._last_request_at)
            if self._last_request_at and delay > 0:
                time.sleep(delay)
            response = None
            for attempt in range(2):
                try:
                    response = self.session.get(
                        FINNHUB_COMPANY_NEWS_URL,
                        params={"symbol": ticker, "from": start_date.isoformat(), "to": end_date.isoformat()},
                        headers={"X-Finnhub-Token": self.api_key},
                        timeout=self.timeout,
                    )
                    self._last_request_at = time.monotonic()
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    self._last_request_at = time.monotonic()
                    if attempt == 1:
                        logger.warning("Finnhub request failed for %s after retry: %s", ticker, exc)
            if response is None or response.status_code >= 400:
                continue
            for item in response.json():
                record = self.normalize(item, ticker)
                key = record.metadata.get("provider_article_id") or record.url or (ticker + record.headline)
                deduped[key] = record
        records = sorted(deduped.values(), key=lambda row: row.event_datetime, reverse=True)
        if self.on_article is not None:
            delivered = []
            for record in records:
                article = self.dispatch(record)
                if article is not None:
                    delivered.append(article)
            return delivered
        return records
