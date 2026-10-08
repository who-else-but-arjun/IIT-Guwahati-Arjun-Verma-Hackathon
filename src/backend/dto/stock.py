"""Typed stock-price, ticker, and correlation graph DTOs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from .decay import decay_factor
from constants import SENTIMENT_HALF_LIFE_HOURS
from .news import SentimentDTO

if TYPE_CHECKING:
    from models.documents import Ticker, TickerData


class TickerNameDTO(BaseModel):
    ticker_id: str = Field(min_length=1)
    company_name: str = ""

    @field_validator("ticker_id", mode="before")
    @classmethod
    def normalize_ticker_id(cls, value: str) -> str:
        return str(value).strip().upper().replace("$", "").replace("-", ".")


class StockBarDTO(BaseModel):
    ticker_id: str = Field(min_length=1)
    timestamp: datetime
    open: float | None = Field(default=None, ge=0.0)
    high: float | None = Field(default=None, ge=0.0)
    low: float | None = Field(default=None, ge=0.0)
    close: float | None = Field(default=None, ge=0.0)
    adj_close: float | None = Field(default=None, ge=0.0)
    volume: int | None = Field(default=None, ge=0)
    dividends: float = Field(default=0.0, ge=0.0)
    stock_splits: float = Field(default=0.0, ge=0.0)

    @field_validator("ticker_id", mode="before")
    @classmethod
    def normalize_ticker_id(cls, value: str) -> str:
        return str(value).strip().upper().replace("$", "").replace("-", ".")

    def to_model(self) -> TickerData:
        from models.documents import TickerData
        return TickerData.from_dto(self)

    @classmethod
    def from_model(cls, model: TickerData, ticker_id: str) -> StockBarDTO:
        payload = model.model_dump(mode="python", by_alias=False)
        payload["ticker_id"] = ticker_id
        return cls.model_validate(payload)


class TickerScoreDTO(BaseModel):
    sentiment: SentimentDTO = Field(default_factory=SentimentDTO)
    delta_score: float = Field(default=0.0, ge=-2.0, le=2.0)

    def effective_score(self, *, as_of: datetime | None = None, fallback_time: datetime | None = None) -> float:
        stamp = self.sentiment.scored_at or fallback_time
        value = self.sentiment.score * decay_factor(stamp, as_of=as_of, half_life_hours=SENTIMENT_HALF_LIFE_HOURS)
        return max(-1.0, min(1.0, value))

    def effective_impact(self, *, as_of: datetime | None = None, fallback_time: datetime | None = None) -> float:
        return self.sentiment.impact_score


class TickerGraphDTO(BaseModel):
    ticker_name: str
    # Keys are canonical ticker symbols; each edge is a Pearson-like correlation.
    correlations: dict[str, float] = Field(default_factory=dict)

    @field_validator("correlations")
    @classmethod
    def validate_correlations(cls, value: dict[str, float]) -> dict[str, float]:
        normalized = {key.strip().upper().replace("-", "."): score for key, score in value.items()}
        if any(score < -1.0 or score > 1.0 for score in normalized.values()):
            raise ValueError("ticker correlations must be between -1 and 1")
        return normalized


class RelevantEventDTO(BaseModel):
    event_id: str = Field(min_length=1)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scored_at: datetime | None = None

    def effective_score(self, *, as_of: datetime | None = None, event_time: datetime | None = None) -> float:
        return self.relevance_score


class EffectiveTickerScoresDTO(BaseModel):
    ticker_id: str
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0)
    relevant_events: list[RelevantEventDTO]


class TickerDTO(BaseModel):
    ticker_name: TickerNameDTO
    logo_url: str | None = None
    ticker_data: list[StockBarDTO] = Field(default_factory=list)
    ticker_score: TickerScoreDTO = Field(default_factory=TickerScoreDTO)
    relevant_events: list[RelevantEventDTO] = Field(default_factory=list)
    ticker_graph: TickerGraphDTO | None = None

    def effective_scores(self, *, as_of: datetime | None = None) -> EffectiveTickerScoresDTO:
        current = as_of or datetime.now(timezone.utc)
        latest_event_time = max((item.scored_at for item in self.relevant_events if item.scored_at), default=None)
        relevant = [
            item.model_copy(update={"relevance_score": item.effective_score(as_of=current)})
            for item in self.relevant_events
        ]
        return EffectiveTickerScoresDTO(
            ticker_id=self.ticker_name.ticker_id,
            sentiment_score=self.ticker_score.effective_score(as_of=current, fallback_time=latest_event_time),
            impact_score=self.ticker_score.effective_impact(as_of=current, fallback_time=latest_event_time),
            relevant_events=relevant,
        )

    def effective_sentiment_score(self, *, as_of: datetime | None = None) -> float:
        return self.effective_scores(as_of=as_of).sentiment_score

    def effective_relevant_events(self, *, as_of: datetime | None = None) -> list[RelevantEventDTO]:
        return self.effective_scores(as_of=as_of).relevant_events

    def to_model(self) -> Ticker:
        from models.documents import Ticker
        return Ticker.from_dto(self)

    @classmethod
    def from_model(cls, model: Ticker) -> TickerDTO:
        payload = model.model_dump(mode="python", by_alias=False)
        payload.pop("id", None)
        payload.pop("updated_at", None)
        return cls.model_validate(payload)
