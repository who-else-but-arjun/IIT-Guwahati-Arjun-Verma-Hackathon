"""Typed Pydantic documents stored in MongoDB."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Annotated

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, Field, field_validator

from dto.news import NewsCategory, SentimentTag
from utils.mongo_utils import object_id_string


MongoId = Annotated[str, BeforeValidator(object_id_string)]

if TYPE_CHECKING:
    from dto.news import NewsEventDTO
    from dto.stock import StockBarDTO, TickerDTO


class SentimentDocument(BaseModel):
    score: float = Field(default=0.0, ge=-1.0, le=1.0)
    tag: SentimentTag = SentimentTag.NEUTRAL
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scored_at: datetime | None = None


class RelevantTickerDocument(BaseModel):
    ticker_id: str = Field(min_length=1)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scored_at: datetime | None = None

    @field_validator("ticker_id", mode="before")
    @classmethod
    def canonical_ticker(cls, value: str) -> str:
        return str(value).strip().upper().replace("$", "").replace("-", ".")


class NewsEvent(BaseModel):
    id: MongoId = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    headline: str
    text: str = ""
    date: date
    time: time
    event_timestamp: datetime | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    category: NewsCategory | None = None
    sentiment: SentimentDocument | None = None
    relevant_tickers: list[RelevantTickerDocument] = Field(default_factory=list)
    url: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_dto(cls, dto: NewsEventDTO) -> "NewsEvent":
        payload = dto.model_dump(mode="python")
        payload["event_timestamp"] = dto.event_datetime
        return cls.model_validate(payload)

    def to_dto(self) -> NewsEventDTO:
        from dto.news import NewsEventDTO
        payload = self.model_dump(mode="python", by_alias=False)
        payload["event_id"] = str(self.id)
        payload.pop("created_at", None)
        payload.pop("event_timestamp", None)
        return NewsEventDTO.model_validate(payload)


class TickerNameDocument(BaseModel):
    ticker_id: str = Field(min_length=1)
    company_name: str = ""

    @field_validator("ticker_id", mode="before")
    @classmethod
    def canonical_ticker(cls, value: str) -> str:
        return str(value).strip().upper().replace("$", "").replace("-", ".")


class TickerData(BaseModel):
    timestamp: datetime
    open: float | None = Field(default=None, ge=0.0)
    high: float | None = Field(default=None, ge=0.0)
    low: float | None = Field(default=None, ge=0.0)
    close: float | None = Field(default=None, ge=0.0)
    adj_close: float | None = Field(default=None, ge=0.0)
    volume: int | None = Field(default=None, ge=0)
    dividends: float = Field(default=0.0, ge=0.0)
    stock_splits: float = Field(default=0.0, ge=0.0)

    @classmethod
    def from_dto(cls, dto: StockBarDTO) -> "TickerData":
        return cls.model_validate(dto.model_dump(mode="python", exclude={"ticker_id"}))

    def to_dto(self, ticker_id: str) -> StockBarDTO:
        from dto.stock import StockBarDTO
        return StockBarDTO.model_validate({"ticker_id": ticker_id, **self.model_dump(mode="python")})


class TickerScoreDocument(BaseModel):
    sentiment: SentimentDocument = Field(default_factory=SentimentDocument)
    delta_score: float = Field(default=0.0, ge=-2.0, le=2.0)


class RelevantEventDocument(BaseModel):
    event_id: str = Field(min_length=1)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scored_at: datetime | None = None


class TickerGraphDocument(BaseModel):
    ticker_name: str
    correlations: dict[str, float] = Field(default_factory=dict)

    @field_validator("correlations")
    @classmethod
    def bounded_correlations(cls, value: dict[str, float]) -> dict[str, float]:
        normalized = {key.strip().upper().replace("-", "."): score for key, score in value.items()}
        if any(score < -1.0 or score > 1.0 for score in normalized.values()):
            raise ValueError("correlation scores must be between -1 and 1")
        return normalized


class Ticker(BaseModel):
    id: MongoId = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    ticker_name: TickerNameDocument
    # Optional persisted company-mark URL. The frontend only renders this value
    # when it is present in the ticker record; it never builds logo URLs itself.
    logo_url: str | None = None
    ticker_score: TickerScoreDocument = Field(default_factory=TickerScoreDocument)
    relevant_events: list[RelevantEventDocument] = Field(default_factory=list)
    ticker_graph: TickerGraphDocument | None = None
    score_update_event_ids: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_dto(cls, dto: TickerDTO) -> "Ticker":
        payload = dto.model_dump(mode="python")
        payload.pop("ticker_data", None)
        return cls.model_validate(payload)

    def to_dto(self) -> TickerDTO:
        from dto.stock import TickerDTO
        payload = self.model_dump(mode="python", by_alias=False)
        payload.pop("id", None)
        payload.pop("updated_at", None)
        payload.pop("score_update_event_ids", None)
        payload["ticker_data"] = []
        return TickerDTO.model_validate(payload)
