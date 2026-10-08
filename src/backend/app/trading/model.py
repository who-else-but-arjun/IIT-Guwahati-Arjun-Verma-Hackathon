"""Typed MongoDB documents for paper portfolios and their performance."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Annotated

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.trading.constants import (
    BENCHMARK_TICKER,
    MAX_POSITION_WEIGHT,
    MIN_NEWS_IMPACT_SCORE,
    NEWS_WEIGHT_STEP,
    PORTFOLIO_SIZE,
    RS_CANDIDATE_COUNT,
    RS_LOOKBACK_DAYS,
    SENTIMENT_DELTA_THRESHOLD,
    STATIC_REBALANCE_DAYS,
    TRANSACTION_COST,
    VOLUME_SPIKE_RATIO,
)
from utils.mongo_utils import object_id_string

MongoId = Annotated[str, BeforeValidator(object_id_string)]


class PortfolioStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PendingRebalanceStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PortfolioConfig(BaseModel):
    benchmark_ticker: str = BENCHMARK_TICKER
    rebalance_days: int = Field(default=STATIC_REBALANCE_DAYS, ge=1, le=365)
    rs_lookback_days: int = Field(default=RS_LOOKBACK_DAYS, ge=20, le=1000)
    candidate_count: int = Field(default=RS_CANDIDATE_COUNT, ge=1, le=101)
    portfolio_size: int = Field(default=PORTFOLIO_SIZE, ge=1, le=101)
    volume_spike_ratio: float = Field(default=VOLUME_SPIKE_RATIO, gt=1.0, le=10.0)
    sentiment_delta_threshold: float = Field(default=SENTIMENT_DELTA_THRESHOLD, gt=0.0, le=2.0)
    min_news_impact_score: float = Field(default=MIN_NEWS_IMPACT_SCORE, ge=0.0, le=1.0)
    news_weight_step: float = Field(default=NEWS_WEIGHT_STEP, gt=0.0, le=0.10)
    max_position_weight: float = Field(default=MAX_POSITION_WEIGHT, gt=0.0, le=1.0)
    transaction_cost: float = Field(default=TRANSACTION_COST, ge=0.0, le=0.1)


class PortfolioPosition(BaseModel):
    ticker_id: str = Field(min_length=1)
    shares: int = Field(ge=0)
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    average_cost: float = Field(default=0.0, ge=0.0)
    last_price: float = Field(default=0.0, ge=0.0)
    market_value: float = Field(default=0.0, ge=0.0)
    unrealized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("ticker_id", mode="before")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return str(value).strip().upper().replace("-", ".")


class PortfolioValuePoint(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_value: float = Field(ge=0.0)
    cash: float = Field(ge=0.0)
    invested_value: float = Field(ge=0.0)
    benchmark_value: float | None = Field(default=None, ge=0.0)


class PortfolioDailyMetrics(BaseModel):
    date: datetime
    portfolio_value: float = Field(ge=0.0)
    # Daily end-of-session position weights, keyed by ticker symbol.
    # Defaults keep existing stored portfolio documents readable.
    position_weights: dict[str, float] = Field(default_factory=dict)
    daily_pnl: float
    daily_return: float
    cumulative_pnl: float
    cumulative_return: float
    drawdown: float = Field(le=0.0)
    annualized_volatility: float = Field(default=0.0, ge=0.0)
    sharpe_ratio: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    turnover: float = Field(default=0.0, ge=0.0)
    transaction_cost: float = Field(default=0.0, ge=0.0)
    benchmark_return: float | None = None


class Portfolio(BaseModel):
    """Portfolio aggregate; orders are stored separately to keep it bounded."""

    id: MongoId = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    name: str = Field(default="News-Driven S&P 100", min_length=1, max_length=100)
    status: PortfolioStatus = PortfolioStatus.ACTIVE
    news_enabled: bool = False
    currency: str = "USD"
    initial_capital: float = Field(gt=0.0)
    cash: float = Field(ge=0.0)
    portfolio_value: float = Field(ge=0.0)
    benchmark_initial_price: float | None = Field(default=None, gt=0.0)
    benchmark_value: float | None = Field(default=None, ge=0.0)
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    peak_value: float = Field(ge=0.0)
    strategy_started_at: date | None = None
    last_processed_session: date | None = None
    backtest_complete: bool = False
    positions: list[PortfolioPosition] = Field(default_factory=list)
    daily_metrics: list[PortfolioDailyMetrics] = Field(default_factory=list)
    value_history: list[PortfolioValuePoint] = Field(default_factory=list)
    config: PortfolioConfig = Field(default_factory=PortfolioConfig)
    last_rebalanced_at: datetime | None = None
    last_rebalance_trigger: str | None = None
    last_news_event_id: str | None = None
    processed_news_event_ids: list[str] = Field(default_factory=list)
    order_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TradeOrder(BaseModel):
    id: MongoId = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    portfolio_id: str
    ticker_id: str
    side: OrderSide
    quantity: int = Field(gt=0)
    price: float = Field(gt=0.0)
    gross_value: float = Field(gt=0.0)
    transaction_cost: float = Field(ge=0.0)
    net_cash_change: float
    event_id: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingRebalance(BaseModel):
    """Deferred portfolio target weights, filled at the next session's open."""

    id: str = Field(alias="_id")
    portfolio_id: str
    event_ids: list[str] = Field(default_factory=list)
    ticker_event_ids: dict[str, list[str]] = Field(default_factory=dict)
    decision_at: datetime
    scheduled_for: datetime
    reason: str
    target_weights: dict[str, float]
    news_filter_applied: bool = False
    status: PendingRebalanceStatus = PendingRebalanceStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None
    executed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("target_weights")
    @classmethod
    def validate_target_weights(cls, value: dict[str, float]) -> dict[str, float]:
        normalized = {key.strip().upper().replace("-", "."): float(weight) for key, weight in value.items()}
        if any(not 0.0 <= weight <= 1.0 for weight in normalized.values()):
            raise ValueError("target weights must be between 0 and 1")
        return normalized
