"""Market data access owned by the isolated trading application."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as market_calendars
import yfinance as yf

from app.trading.constants import SP100_TICKERS
from services.redis.cache import make_cache_key, remember_with_stale

FIELDS = ("Open", "High", "Low", "Close", "Volume")
NEW_YORK = ZoneInfo("America/New_York")


def download_daily_bars(tickers: list[str] | tuple[str, ...] = SP100_TICKERS, *, period: str | None = "5y",
                        start: str | None = None, end: str | None = None) -> dict[str, pd.DataFrame]:
    """Download/cache adjusted bars, retaining the last good set on Yahoo outages."""
    symbols = list(dict.fromkeys(str(item).strip().upper() for item in tickers))
    if not symbols:
        return {field: pd.DataFrame() for field in FIELDS}

    key = make_cache_key("trading-daily-bars", sorted(symbols), period, start, end)
    timeout = 60 if period in {"5d", "10d", "1mo"} else 900
    return remember_with_stale(
        key,
        lambda: _download_daily_bars(symbols, period=period, start=start, end=end),
        timeout=timeout,
        stale_timeout=7 * 24 * 60 * 60,
    )


def _download_daily_bars(symbols: list[str], *, period: str | None,
                         start: str | None, end: str | None) -> dict[str, pd.DataFrame]:
    date_range = {"start": start, "end": end} if start is not None else {"period": period or "5y"}
    frame = yf.download(
        tickers=[ticker.replace(".", "-") for ticker in symbols],
        **date_range,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=False,
    )
    result = {field: _extract_field(frame, field) for field in FIELDS}
    if not any(not data.empty for data in result.values()):
        raise RuntimeError("Yahoo Finance returned no usable daily bars.")
    if len(symbols) == 1:
        for data in result.values():
            if data.shape[1] == 1:
                data.columns = symbols
    return result


def download_open_prices_on(tickers: list[str], session_date: str) -> dict[str, float]:
    """Read a specific session's daily-bar open, retrying until Yahoo exposes it."""
    symbols = list(dict.fromkeys(str(item).strip().upper() for item in tickers))
    bars = download_daily_bars(symbols, period="10d")
    opens = bars["Open"]
    if opens.empty:
        raise RuntimeError("Yahoo Finance returned no daily open prices for pending orders.")
    session = pd.Timestamp(session_date).normalize()
    day_rows = opens.loc[opens.index.normalize() == session]
    prices: dict[str, float] = {}
    if not day_rows.empty:
        row = day_rows.iloc[-1]
        for symbol in symbols:
            if symbol in row and pd.notna(row[symbol]) and float(row[symbol]) > 0:
                prices[symbol] = float(row[symbol])
    missing = set(symbols) - prices.keys()
    if missing:
        raise RuntimeError(
            f"Daily open is not published yet for {', '.join(sorted(missing))} on {session_date}."
        )
    return prices


def next_session_open(decision_at: datetime | None = None) -> datetime:
    """Return the next NYSE session open strictly after the decision's local date."""
    local = (decision_at or datetime.now(timezone.utc)).astimezone(NEW_YORK)
    first = local.date() + timedelta(days=1)
    schedule = market_calendars.get_calendar("NYSE").schedule(
        start_date=first,
        end_date=first + timedelta(days=14),
    )
    if schedule.empty:
        raise RuntimeError("NYSE calendar returned no upcoming trading session.")
    return schedule.iloc[0]["market_open"].to_pydatetime().astimezone(timezone.utc)


def latest_completed_session(now: datetime | None = None):
    """Return the latest NYSE session whose close has passed."""
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_date = instant.astimezone(NEW_YORK).date()
    schedule = market_calendars.get_calendar("NYSE").schedule(
        start_date=local_date - timedelta(days=14), end_date=local_date,
    )
    completed = schedule[schedule["market_close"] <= pd.Timestamp(instant)]
    return completed.index[-1].date() if not completed.empty else None


def download_universe(period: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download adjusted closes and volume bars for the configured universe."""
    bars = download_daily_bars(SP100_TICKERS, period=period)
    return bars["Close"], bars["Volume"]


def download_latest_prices(tickers: list[str], *, period: str = "5d") -> dict[str, float]:
    symbols = list(dict.fromkeys(tickers))
    if not symbols:
        return {}
    key = make_cache_key("trading-latest-prices", sorted(symbols), period)
    return remember_with_stale(
        key,
        lambda: _download_latest_prices(symbols, period=period),
        timeout=180,
        stale_timeout=24 * 60 * 60,
    )


def _download_latest_prices(symbols: list[str], *, period: str) -> dict[str, float]:
    frame = yf.download(
        tickers=[ticker.replace(".", "-") for ticker in symbols],
        period=period,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=False,
    )
    close = _extract_field(frame, "Close")
    if len(symbols) == 1 and close.shape[1] == 1:
        close.columns = symbols
    prices = {}
    for symbol in symbols:
        if symbol in close.columns:
            observations = close[symbol].dropna()
            if not observations.empty and float(observations.iloc[-1]) > 0:
                prices[symbol] = float(observations.iloc[-1])
    missing = set(symbols) - prices.keys()
    if missing:
        raise RuntimeError(f"No recent market price available for: {', '.join(sorted(missing))}.")
    return prices


def _extract_field(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    columns = frame.columns
    if not isinstance(columns, pd.MultiIndex):
        if field not in columns:
            return pd.DataFrame()
        return frame[[field]].rename(columns={field: "single"})
    level_values = [set(columns.get_level_values(level)) for level in range(columns.nlevels)]
    field_level = next((index for index, values in enumerate(level_values) if field in values), None)
    if field_level is None:
        return pd.DataFrame()
    output = frame.xs(field, axis=1, level=field_level, drop_level=True)
    if isinstance(output, pd.Series):
        output = output.to_frame(name="single")
    if isinstance(output.columns, pd.MultiIndex):
        output.columns = output.columns.get_level_values(0)
    output.columns = [str(column).replace("-", ".") for column in output.columns]
    output.index = pd.to_datetime(output.index).normalize()
    return output.sort_index()
