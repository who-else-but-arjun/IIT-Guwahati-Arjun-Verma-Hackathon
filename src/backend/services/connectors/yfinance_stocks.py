"""Historical/latest market-price connector for S&P 100 stocks via yfinance."""

import pandas as pd
import yfinance as yf

from dto.stock import StockBarDTO
from services.redis.cache import make_cache_key, remember

from utils.stock_utils import filter_sp100, yahoo_symbol


class YFinanceStocksConnector:
    def get_history(self, symbols, *, period="5d", interval="1d", start=None, end=None):
        tickers = filter_sp100(symbols)
        if not tickers:
            return []
        key = make_cache_key("yfinance-history", sorted(tickers), period, interval, start, end)

        def load_history():
            return self._download_history(tickers, period=period, interval=interval, start=start, end=end)

        # Daily bars remain useful across page refreshes; intraday bars expire
        # quickly so live prices stay responsive during a trading session.
        timeout = 3600 if interval.endswith("d") or interval.endswith("wk") or interval.endswith("mo") else 120
        return remember(key, load_history, timeout)

    def _download_history(self, tickers, *, period, interval, start, end):
        yahoo_tickers = [yahoo_symbol(symbol) for symbol in tickers]
        frame = yf.download(
            tickers=yahoo_tickers,
            period=period if start is None else None,
            start=start,
            end=end,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
        )
        if frame is None or frame.empty:
            return []
        result = []
        for canonical, yahoo_ticker in zip(tickers, yahoo_tickers):
            if getattr(frame.columns, "nlevels", 1) > 1:
                levels = frame.columns.get_level_values(0)
                if yahoo_ticker in levels:
                    prices = frame.xs(yahoo_ticker, axis=1, level=0)
                elif yahoo_ticker in frame.columns.get_level_values(1):
                    prices = frame.xs(yahoo_ticker, axis=1, level=1)
                else:
                    continue
            elif len(tickers) == 1:
                prices = frame
            else:
                continue
            prices = prices.dropna(how="all")
            for timestamp, row in prices.iterrows():
                record = {"ticker_id": canonical, "timestamp": timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp}
                for field in ("Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"):
                    if field not in row.index:
                        continue
                    value = row[field]
                    if value is None or pd.isna(value):
                        continue
                    key = field.lower().replace(" ", "_")
                    record[key] = float(value) if key != "volume" else int(value)
                result.append(StockBarDTO.model_validate(record))
        return result
