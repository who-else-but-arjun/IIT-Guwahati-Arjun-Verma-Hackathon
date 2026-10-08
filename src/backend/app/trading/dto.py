"""API-facing DTOs and conversions for portfolio documents."""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.trading.model import (
    OrderSide,
    Portfolio,
    PortfolioConfig,
    PortfolioDailyMetrics as PortfolioDailyMetricsModel,
    PortfolioPosition,
    PortfolioStatus,
    PendingRebalance,
    PortfolioValuePoint as PortfolioValuePointModel,
    TradeOrder,
)
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


class PortfolioConfigDTO(BaseModel):
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

    @classmethod
    def from_model(cls, model: PortfolioConfig) -> "PortfolioConfigDTO":
        return cls.model_validate(model.model_dump(mode="python"))

    def to_model(self) -> PortfolioConfig:
        return PortfolioConfig.model_validate(self.model_dump(mode="python"))


class PortfolioConfigPatchDTO(BaseModel):
    benchmark_ticker: str | None = None
    rebalance_days: int | None = Field(default=None, ge=1, le=365)
    rs_lookback_days: int | None = Field(default=None, ge=20, le=1000)
    candidate_count: int | None = Field(default=None, ge=1, le=101)
    portfolio_size: int | None = Field(default=None, ge=1, le=101)
    volume_spike_ratio: float | None = Field(default=None, gt=1.0, le=10.0)
    sentiment_delta_threshold: float | None = Field(default=None, gt=0.0, le=2.0)
    min_news_impact_score: float | None = Field(default=None, ge=0.0, le=1.0)
    news_weight_step: float | None = Field(default=None, gt=0.0, le=0.10)
    max_position_weight: float | None = Field(default=None, gt=0.0, le=1.0)
    transaction_cost: float | None = Field(default=None, ge=0.0, le=0.1)


class CreatePortfolioDTO(BaseModel):
    name: str = Field(default="News-Driven S&P 100", min_length=1, max_length=100)
    initial_capital: float = Field(gt=0.0)
    news_enabled: bool = False
    config: PortfolioConfigDTO = Field(default_factory=PortfolioConfigDTO)


class PortfolioPatchDTO(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: PortfolioStatus | None = None
    news_enabled: bool | None = None
    config: PortfolioConfigPatchDTO | None = None


class PortfolioPositionDTO(BaseModel):
    ticker_id: str
    shares: int
    weight: float
    average_cost: float
    last_price: float
    market_value: float
    unrealized_pnl: float
    updated_at: datetime

    @classmethod
    def from_model(cls, model: PortfolioPosition) -> "PortfolioPositionDTO":
        return cls.model_validate(model.model_dump(mode="python"))


class PortfolioValuePointDTO(BaseModel):
    timestamp: datetime
    total_value: float
    cash: float
    invested_value: float
    benchmark_value: float | None

    @classmethod
    def from_model(cls, model: PortfolioValuePointModel) -> "PortfolioValuePointDTO":
        return cls.model_validate(model.model_dump(mode="python"))


class PortfolioDailyMetricsDTO(BaseModel):
    date: datetime
    portfolio_value: float
    position_weights: dict[str, float] = Field(default_factory=dict)
    daily_pnl: float
    daily_return: float
    cumulative_pnl: float
    cumulative_return: float
    drawdown: float
    annualized_volatility: float
    sharpe_ratio: float
    realized_pnl: float
    unrealized_pnl: float
    turnover: float
    transaction_cost: float
    benchmark_return: float | None

    @classmethod
    def from_model(cls, model: PortfolioDailyMetricsModel) -> "PortfolioDailyMetricsDTO":
        return cls.model_validate(model.model_dump(mode="python"))


class PortfolioDTO(BaseModel):
    id: str
    name: str
    status: PortfolioStatus
    news_enabled: bool
    currency: str
    initial_capital: float
    cash: float
    portfolio_value: float
    benchmark_initial_price: float | None
    benchmark_value: float | None
    total_realized_pnl: float
    total_unrealized_pnl: float
    peak_value: float
    strategy_started_at: date | None
    last_processed_session: date | None
    backtest_complete: bool
    positions: list[PortfolioPositionDTO]
    daily_metrics: list[PortfolioDailyMetricsDTO]
    value_history: list[PortfolioValuePointDTO]
    config: PortfolioConfigDTO
    last_rebalanced_at: datetime | None
    last_rebalance_trigger: str | None
    last_news_event_id: str | None
    order_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, model: Portfolio) -> "PortfolioDTO":
        return cls(
            id=model.id,
            name=model.name,
            status=model.status,
            news_enabled=model.news_enabled,
            currency=model.currency,
            initial_capital=model.initial_capital,
            cash=model.cash,
            portfolio_value=model.portfolio_value,
            benchmark_initial_price=model.benchmark_initial_price,
            benchmark_value=model.benchmark_value,
            total_realized_pnl=model.total_realized_pnl,
            total_unrealized_pnl=model.total_unrealized_pnl,
            peak_value=model.peak_value,
            strategy_started_at=model.strategy_started_at,
            last_processed_session=model.last_processed_session,
            backtest_complete=model.backtest_complete,
            positions=[PortfolioPositionDTO.from_model(item) for item in model.positions],
            daily_metrics=[PortfolioDailyMetricsDTO.from_model(item) for item in model.daily_metrics],
            value_history=[PortfolioValuePointDTO.from_model(item) for item in model.value_history],
            config=PortfolioConfigDTO.from_model(model.config),
            last_rebalanced_at=model.last_rebalanced_at,
            last_rebalance_trigger=model.last_rebalance_trigger,
            last_news_event_id=model.last_news_event_id,
            order_count=model.order_count,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class OrderRequestDTO(BaseModel):
    ticker_id: str = Field(min_length=1)
    side: OrderSide
    quantity: int = Field(gt=0)
    event_id: str | None = None
    reason: str = "manual"

    @field_validator("ticker_id", mode="before")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return str(value).strip().upper().replace("-", ".")


class TradeOrderDTO(BaseModel):
    id: str
    portfolio_id: str
    ticker_id: str
    side: OrderSide
    quantity: int
    price: float
    gross_value: float
    transaction_cost: float
    net_cash_change: float
    event_id: str | None
    event_ids: list[str] = Field(default_factory=list)
    reason: str
    created_at: datetime

    @classmethod
    def from_model(cls, model: TradeOrder) -> "TradeOrderDTO":
        return cls(
            id=model.id,
            portfolio_id=model.portfolio_id,
            ticker_id=model.ticker_id,
            side=model.side,
            quantity=model.quantity,
            price=model.price,
            gross_value=model.gross_value,
            transaction_cost=model.transaction_cost,
            net_cash_change=model.net_cash_change,
            event_id=model.event_id,
            event_ids=model.event_ids,
            reason=model.reason,
            created_at=model.created_at,
        )


class PendingRebalanceDTO(BaseModel):
    id: str
    portfolio_id: str
    event_ids: list[str]
    ticker_event_ids: dict[str, list[str]] = Field(default_factory=dict)
    decision_at: datetime
    scheduled_for: datetime
    reason: str
    target_weights: dict[str, float]
    news_filter_applied: bool = False
    status: str
    attempts: int
    last_error: str | None
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, model: PendingRebalance) -> "PendingRebalanceDTO":
        return cls.model_validate(model.model_dump(mode="python", by_alias=False))
