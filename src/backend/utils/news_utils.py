"""Shared helpers for constructing normalized news event DTOs."""

from datetime import date, datetime, time
from hashlib import sha256
from typing import Sequence

from dto.news import NewsEventDTO, RelevantTickerDTO
from utils.datetime_utils import parse_datetime
from utils.stock_utils import filter_sp100
from utils.text_utils import clean_news_text


def build_news_event(*, provider: str, article_id: str | int | None, headline: str | None,
                     summary: str = "", content: str = "", url: str = "", source: str = "",
                     author: str = "", published_at: datetime | str | int | float | None = None,
                     updated_at: datetime | str | int | float | None = None, text_kind: str | None = None,
                     symbols: Sequence[str] | str | None = None) -> NewsEventDTO:
    published = parse_datetime(published_at)
    clean_headline = clean_news_text(headline)
    clean_summary = clean_news_text(summary)
    clean_content = clean_news_text(content)
    related = filter_sp100(symbols)
    stable_id = str(article_id) if article_id is not None else sha256(
        f"{provider}|{url}|{published.isoformat()}|{clean_headline}".encode("utf-8")
    ).hexdigest()
    metadata: dict[str, str | int | float | bool | None] = {
        "provider": provider,
        "provider_article_id": stable_id,
        "source": source or provider,
        "author": author,
        "summary": clean_summary,
        "text_kind": text_kind or ("article_body" if clean_content else "summary"),
        "updated_at": str(updated_at) if updated_at is not None else None,
    }
    return NewsEventDTO(
        headline=clean_headline, text=clean_content or clean_summary,
        date=date(published.year, published.month, published.day),
        time=time(published.hour, published.minute, published.second, published.microsecond, tzinfo=published.tzinfo),
        metadata=metadata,
        relevant_tickers=[RelevantTickerDTO(ticker_id=symbol) for symbol in related],
        url=url or None,
    )
