"""News, sentiment, and article-to-ticker DTOs."""

from __future__ import annotations

from datetime import date as Date, datetime, time as Time, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from constants import SentimentTag, NewsCategory

if TYPE_CHECKING:
    from models.documents import NewsEvent

MetadataScalar = str | int | float | bool | None


class SentimentDTO(BaseModel):
    score: float = Field(default=0.0, ge=-1.0, le=1.0)
    tag: SentimentTag = SentimentTag.NEUTRAL
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scored_at: datetime | None = None

    def effective_score(self, *, as_of: datetime | None = None, half_life_hours: float = 72.0,
                        fallback_time: datetime | None = None) -> float:
        """Return event sentiment unchanged; only aggregate ticker sentiment decays."""
        return self.score

    def effective_impact(self, *, as_of: datetime | None = None, half_life_hours: float = 48.0,
                         fallback_time: datetime | None = None) -> float:
        """Return event impact unchanged."""
        return self.impact_score


class RelevantTickerDTO(BaseModel):
    ticker_id: str = Field(min_length=1, description="Canonical ticker symbol, for example AMZN")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scored_at: datetime | None = None

    @field_validator("ticker_id", mode="before")
    @classmethod
    def normalize_ticker_id(cls, value: str) -> str:
        return str(value).strip().upper().replace("$", "").replace("-", ".")

    def effective_score(self, *, as_of: datetime | None = None, event_time: datetime | None = None,
                        half_life_hours: float = 36.0) -> float:
        """Return event-ticker relevance unchanged."""
        return self.relevance_score


class EffectiveTickerRelevanceDTO(BaseModel):
    ticker_id: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class EffectiveNewsScoresDTO(BaseModel):
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0)
    relevant_tickers: list[EffectiveTickerRelevanceDTO]


class NewsEventDTO(BaseModel):
    event_id: str | None = None
    headline: str
    text: str = ""
    date: Date
    time: Time
    metadata: dict[str, MetadataScalar] = Field(default_factory=dict)
    category: NewsCategory | None = None
    sentiment: SentimentDTO | None = None
    relevant_tickers: list[RelevantTickerDTO] = Field(default_factory=list)
    url: str | None = None

    @property
    def event_datetime(self) -> datetime:
        value = datetime.combine(self.date, self.time)
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def effective_scores(self, *, as_of: datetime | None = None) -> EffectiveNewsScoresDTO:
        sentiment = self.sentiment or SentimentDTO()
        event_time = self.event_datetime
        effective_sentiment = sentiment.effective_score(as_of=as_of, fallback_time=event_time)
        effective_impact = sentiment.effective_impact(as_of=as_of, fallback_time=event_time)
        related = [
            EffectiveTickerRelevanceDTO(
                ticker_id=item.ticker_id,
                relevance_score=item.effective_score(as_of=as_of, event_time=event_time),
            )
            for item in self.relevant_tickers
        ]
        return EffectiveNewsScoresDTO(
            sentiment_score=max(-1.0, min(1.0, effective_sentiment)),
            impact_score=max(0.0, min(1.0, effective_impact)),
            relevant_tickers=related,
        )

    def with_effective_scores(self, *, as_of: datetime | None = None) -> NewsEventDTO:
        """Return a response copy with effective values; event scores stay unchanged."""
        effective = self.effective_scores(as_of=as_of)
        source_sentiment = self.sentiment or SentimentDTO()
        adjusted_sentiment = source_sentiment.model_copy(update={
            "score": effective.sentiment_score,
            "impact_score": effective.impact_score,
        })
        effective_relevance = {item.ticker_id: item.relevance_score for item in effective.relevant_tickers}
        adjusted_tickers = [
            item.model_copy(update={"relevance_score": effective_relevance[item.ticker_id]})
            for item in self.relevant_tickers
        ]
        return self.model_copy(update={"sentiment": adjusted_sentiment, "relevant_tickers": adjusted_tickers})

    def to_model(self) -> NewsEvent:
        from models.documents import NewsEvent
        return NewsEvent.from_dto(self)

    @classmethod
    def from_model(cls, model: NewsEvent) -> NewsEventDTO:
        payload = model.model_dump(mode="python", by_alias=False)
        payload.pop("id", None)
        payload.pop("created_at", None)
        return cls.model_validate(payload)
