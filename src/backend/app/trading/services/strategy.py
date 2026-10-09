"""Residual-strength stock ranking and rebalance-trigger calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
try:
    from scipy.optimize import minimize
except ImportError:  # Keep non-optimization trading endpoints available in stale images.
    minimize = None

from app.trading.constants import VOLUME_BASELINE_DAYS, VOLUME_RECENT_DAYS
from app.trading.model import Portfolio, PortfolioPosition
from app.trading.services.market_data import download_universe


def load_market_data(portfolio: Portfolio) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Load adjusted daily closes and volumes for the S&P 100 plus S&P 500 proxy."""
    period = "2y" if portfolio.config.rs_lookback_days <= 504 else "5y"
    close_frame, volume_frame = download_universe(period)
    benchmark_data = yf.download(
        portfolio.config.benchmark_ticker,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if benchmark_data.empty:
        raise RuntimeError(f"No benchmark data returned for {portfolio.config.benchmark_ticker}.")
    benchmark_close = benchmark_data["Close"]
    if isinstance(benchmark_close, pd.DataFrame):
        benchmark_close = benchmark_close.iloc[:, 0]
    benchmark_close.index = pd.to_datetime(benchmark_close.index).normalize()
    return close_frame, volume_frame, benchmark_close.dropna()


def rank_residual_strength(
    closes: pd.DataFrame, benchmark: pd.Series, *, lookback_days: int, candidate_count: int, portfolio_size: int
) -> list[tuple[str, float]]:
    """Filter by relative performance, then rank log-linear slope times R²."""
    common_dates = closes.index.intersection(benchmark.index)
    history = closes.loc[common_dates].tail(lookback_days)
    benchmark_history = benchmark.loc[common_dates].tail(lookback_days)
    if len(history) < lookback_days or len(benchmark_history) < lookback_days:
        return []

    stock_performance = history.iloc[-1] / history.iloc[0]
    benchmark_performance = float(benchmark_history.iloc[-1] / benchmark_history.iloc[0])
    relative_strength = (stock_performance / benchmark_performance - 1.0).dropna().nlargest(candidate_count)
    x = np.arange(lookback_days, dtype=float)
    scores: list[tuple[str, float]] = []
    for ticker in relative_strength.index:
        prices = history[ticker].dropna()
        if len(prices) != lookback_days or (prices <= 0).any():
            continue
        log_prices = np.log(prices.to_numpy(dtype=float))
        slope, intercept = np.polyfit(x, log_prices, 1)
        residuals = log_prices - (slope * x + intercept)
        total_sum_squares = float(np.square(log_prices - log_prices.mean()).sum())
        r_squared = 0.0 if total_sum_squares == 0 else 1.0 - float(np.square(residuals).sum()) / total_sum_squares
        scores.append((str(ticker), float(slope * r_squared)))
    return sorted(scores, key=lambda item: item[1], reverse=True)[:portfolio_size]


def mean_variance_weights(
    closes: pd.DataFrame,
    tickers: list[str],
    *,
    max_position_weight: float,
    lookback_days: int,
) -> dict[str, float]:
    """Minimize portfolio variance while preserving equal-weight expected return.

    The portfolio stays long-only and respects the configured position cap. If
    the cap makes full investment impossible, the remaining allocation stays
    in cash, matching the existing strategy's capped-weight behavior. A
    diagonal covariance shrinkage and equal-weight fallback keep the optimizer
    stable for short or degenerate price histories.
    """
    selected = list(dict.fromkeys(tickers))
    if not selected:
        return {}

    equal_weight = min(1.0 / len(selected), max_position_weight)
    total_weight = equal_weight * len(selected)
    fallback = {ticker: equal_weight for ticker in selected}
    price_history = closes.reindex(columns=selected).tail(max(lookback_days + 1, 21))
    returns = price_history.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    returns = returns.dropna(how="any")
    if len(returns) < 20:
        return fallback

    expected_returns = returns.mean().to_numpy(dtype=float)
    covariance = returns.cov().to_numpy(dtype=float)
    if not np.isfinite(expected_returns).all() or not np.isfinite(covariance).all():
        return fallback

    # Shrink noisy off-diagonal estimates toward the diagonal and add a small
    # ridge so highly correlated or nearly constant assets remain solvable.
    diagonal = np.diag(np.diag(covariance))
    covariance = 0.8 * covariance + 0.2 * diagonal
    ridge = max(float(np.trace(covariance)) / len(selected), 1e-12) * 1e-6
    covariance += np.eye(len(selected)) * ridge
    target_return = float(np.dot(np.full(len(selected), equal_weight), expected_returns))
    initial = np.full(len(selected), equal_weight, dtype=float)

    # scipy is declared by the service requirements. When an older deployed
    # image lacks it, use the safe equal-weight portfolio rather than failing
    # the entire trading API during URL imports or strategy execution.
    if minimize is None:
        return fallback

    result = minimize(
        fun=lambda weights: float(weights @ covariance @ weights),
        x0=initial,
        method="SLSQP",
        bounds=[(0.0, max_position_weight)] * len(selected),
        constraints=(
            {"type": "eq", "fun": lambda weights: float(weights.sum() - total_weight)},
            {"type": "ineq", "fun": lambda weights: float(weights @ expected_returns - target_return)},
        ),
        options={"maxiter": 200, "ftol": 1e-12},
    )
    if not result.success or not np.isfinite(result.x).all():
        return fallback

    optimized = np.clip(result.x, 0.0, max_position_weight)
    # Remove tiny numerical drift without violating the position cap.
    drift = total_weight - float(optimized.sum())
    for index in np.argsort(-optimized if drift > 0 else optimized):
        adjustment = min(drift, max_position_weight - optimized[index]) if drift > 0 else max(drift, -optimized[index])
        optimized[index] += adjustment
        drift -= adjustment
        if abs(drift) < 1e-10:
            break
    return {ticker: float(weight) for ticker, weight in zip(selected, optimized) if weight > 1e-8}


def rebalance_trigger(portfolio: Portfolio, volumes: pd.DataFrame, now: pd.Timestamp) -> str | None:
    """Check elapsed market sessions and a 5/20-session volume-spike trigger."""
    if portfolio.last_rebalanced_at is None:
        return "initial"
    from app.trading.services.market_data import NEW_YORK

    last_timestamp = pd.Timestamp(portfolio.last_rebalanced_at)
    if last_timestamp.tzinfo is None:
        # Mongo reads UTC values as naive datetimes unless tz_aware is enabled.
        last_timestamp = last_timestamp.tz_localize("UTC")
    current_timestamp = pd.Timestamp(now)
    if current_timestamp.tzinfo is None:
        current_timestamp = current_timestamp.tz_localize("UTC")
    last_rebalanced = last_timestamp.tz_convert(NEW_YORK).date()
    current_session = current_timestamp.tz_convert(NEW_YORK).date()
    sessions = sorted({pd.Timestamp(session).date() for session in volumes.index})
    elapsed_sessions = sum(last_rebalanced < session <= current_session for session in sessions)
    if elapsed_sessions >= portfolio.config.rebalance_days:
        return "static_period"
    if current_session <= last_rebalanced:
        return None
    if not portfolio.positions:
        return None
    recent = volumes.tail(VOLUME_RECENT_DAYS).mean()
    baseline = volumes.tail(VOLUME_BASELINE_DAYS + VOLUME_RECENT_DAYS).head(VOLUME_BASELINE_DAYS).mean()
    common = set(recent.index).intersection(baseline.index, {item.ticker_id for item in portfolio.positions})
    for ticker in common:
        base_volume = float(baseline[ticker])
        if base_volume > 0 and float(recent[ticker]) / base_volume >= portfolio.config.volume_spike_ratio:
            return "volume_spike"
    return None


def current_position_weights(portfolio: Portfolio) -> dict[str, float]:
    total = portfolio.portfolio_value
    if total <= 0:
        return {}
    return {position.ticker_id: position.market_value / total for position in portfolio.positions}


def weights_to_positions(weights: dict[str, float], prices: dict[str, float], total_value: float) -> list[PortfolioPosition]:
    """Convert target weights to whole-share position targets."""
    positions = []
    for ticker, weight in weights.items():
        price = prices.get(ticker, 0.0)
        if price <= 0 or weight <= 0:
            continue
        shares = int(total_value * weight / price)
        if shares:
            positions.append(PortfolioPosition(
                ticker_id=ticker,
                shares=shares,
                weight=weight,
                average_cost=price,
                last_price=price,
                market_value=shares * price,
            ))
    return positions
