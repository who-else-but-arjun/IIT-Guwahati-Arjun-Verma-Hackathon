"""Ticker normalization and stock price/correlation helpers."""

from collections import defaultdict
from collections.abc import Iterable

import pandas as pd

from constants import SP100_SET
from dto.stock import StockBarDTO, TickerGraphDTO


def canonical_symbol(symbol: str) -> str:
    """Normalize provider ticker strings to the project's dot notation."""
    return str(symbol).strip().upper().replace("$", "").replace("-", ".")


def yahoo_symbol(symbol: str) -> str:
    """Translate index symbols to Yahoo Finance's punctuation convention."""
    return canonical_symbol(symbol).replace(".", "-")


def filter_sp100(symbols: object) -> list[str]:
    if isinstance(symbols, str):
        symbols = symbols.replace(",", " ").split()
    if not isinstance(symbols, Iterable):
        return []
    return sorted({canonical_symbol(str(s)) for s in symbols if canonical_symbol(str(s)) in SP100_SET})


def build_stock_correlation_graph(bars: list[StockBarDTO], *, min_observations: int = 252) -> dict[str, TickerGraphDTO]:
    """Build a return-correlation graph; each ticker edge stores correlation."""
    closes: dict[str, dict[str, float]] = defaultdict(dict)
    for bar in bars:
        close = bar.adj_close if bar.adj_close is not None else bar.close
        if close is not None and close > 0:
            closes[bar.ticker_id][bar.timestamp.date().isoformat()] = close
    returns = pd.DataFrame(closes).sort_index().pct_change(fill_method=None)
    correlations = returns.corr(min_periods=min_observations)
    return {
        symbol: TickerGraphDTO(
            ticker_name=symbol,
            correlations={neighbor: float(score) for neighbor, score in correlations[symbol].dropna().items() if neighbor != symbol},
        )
        for symbol in correlations.columns
    }
