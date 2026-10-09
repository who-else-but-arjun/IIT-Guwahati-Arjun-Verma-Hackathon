"""Five-year daily-bar portfolio replay and incremental catch-up."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from bson import ObjectId

from app.trading.constants import (
    BACKTEST_LOOKBACK_CALENDAR_DAYS,
    BACKTEST_NAME,
    BACKTEST_YEARS,
    DEFAULT_INITIAL_CAPITAL,
    GRAPH_PROPAGATION_SCALE,
)
from app.trading.constants import SP100_TICKERS
from app.trading.model import (
    OrderSide,
    Portfolio,
    PortfolioDailyMetrics,
    PortfolioPosition,
    PortfolioValuePoint,
    TradeOrder,
)
from app.trading.services.market_data import download_daily_bars, next_session_open
from app.trading.services.strategy import mean_variance_weights, rank_residual_strength

NEW_YORK = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 15)


def _session_time(session: pd.Timestamp, market_time: time) -> datetime:
    return datetime.combine(session.date(), market_time, tzinfo=NEW_YORK).astimezone(timezone.utc)


def replay_portfolio(repository, portfolio: Portfolio | None = None, *,
                     initial_capital: float = DEFAULT_INITIAL_CAPITAL,
                     until_date: date | None = None,
                     news_events: list[tuple[object, str]] | None = None) -> tuple[Portfolio, int, int]:
    """Bootstrap once from the fixed five-year start, then replay only new sessions.

    Incremental runs fetch a pre-checkpoint warm-up window for the RS signal but
    never re-simulate it. The durable portfolio checkpoint determines where the
    replay loop begins.
    """
    if portfolio is None:
        portfolio = repository.create_portfolio(
            name=BACKTEST_NAME, initial_capital=initial_capital,
        )
    if portfolio.backtest_complete:
        checkpoint = portfolio.last_processed_session or (
            portfolio.value_history[-1].timestamp.date() if portfolio.value_history else None
        )
        if checkpoint is None:
            raise RuntimeError("Completed portfolio is missing its saved replay checkpoint.")
        lookback_days = max(BACKTEST_LOOKBACK_CALENDAR_DAYS, int(portfolio.config.rs_lookback_days * 1.5))
        fetch_start = checkpoint - timedelta(days=lookback_days)
        start_date = fetch_start.isoformat()
    elif portfolio.last_processed_session or portfolio.value_history:
        checkpoint = portfolio.last_processed_session or portfolio.value_history[-1].timestamp.date()
        fetch_start = checkpoint - timedelta(days=max(BACKTEST_LOOKBACK_CALENDAR_DAYS, int(portfolio.config.rs_lookback_days * 1.5)))
        start_date = fetch_start.isoformat()
    else:
        if portfolio.strategy_started_at is None:
            today = datetime.now(NEW_YORK).date()
            try:
                portfolio.strategy_started_at = today.replace(year=today.year - BACKTEST_YEARS)
            except ValueError:  # February 29 to a non-leap year.
                portfolio.strategy_started_at = today.replace(year=today.year - BACKTEST_YEARS, day=28)
            repository.save_portfolio(portfolio)
        start_date = portfolio.strategy_started_at.isoformat()
    today = datetime.now(NEW_YORK).date()
    final_day = until_date or today
    bars = download_daily_bars(
        [*SP100_TICKERS, portfolio.config.benchmark_ticker],
        period=None, start=start_date, end=(final_day + timedelta(days=1)).isoformat(),
    )
    opens, closes, volumes = bars["Open"], bars["Close"], bars["Volume"]
    benchmark = closes[portfolio.config.benchmark_ticker] if portfolio.config.benchmark_ticker in closes else pd.Series(dtype=float)
    if closes.empty or benchmark.dropna().empty:
        raise RuntimeError("Yahoo Finance returned no usable S&P 100/benchmark daily data.")
    common_dates = closes.index.intersection(benchmark.dropna().index).sort_values()
    closes, opens, volumes = closes.reindex(common_dates), opens.reindex(common_dates), volumes.reindex(common_dates)
    benchmark = benchmark.reindex(common_dates).dropna()
    now_local = datetime.now(NEW_YORK)
    completed = common_dates[(common_dates.date < now_local.date()) |
                             ((common_dates.date == now_local.date()) & (now_local.time() >= MARKET_CLOSE))]
    completed = completed[completed.date <= final_day]
    if completed.empty:
        raise RuntimeError("Yahoo Finance has not returned a completed trading session yet.")
    last_close = completed[-1]
    completed = completed[completed <= last_close]

    prior_day = portfolio.last_processed_session or (
        portfolio.value_history[-1].timestamp.date() if portfolio.value_history else None
    )
    first_index = 0
    if prior_day is not None:
        later = np.flatnonzero(np.asarray([stamp.date() > prior_day for stamp in completed]))
        if not len(later):
            return portfolio, 0, 0
        first_index = int(later[0])
    else:
        if portfolio.benchmark_initial_price is None:
            portfolio.benchmark_initial_price = float(benchmark.iloc[0])

    session_dates = list(completed)
    order_rows: list[TradeOrder] = []
    processed_days = 0
    pending_targets: dict[pd.Timestamp, tuple[
        dict[str, float], str, str | None, list[str], dict[str, list[str]], str | None,
    ]] = {}
    for plan in repository.get_pending_rebalances(portfolio_id=portfolio.id):
        session_day = pd.Timestamp(plan.scheduled_for.astimezone(NEW_YORK).date())
        pending_targets[session_day] = (
            dict(plan.target_weights), plan.reason, plan.event_ids[-1] if plan.event_ids else None,
            list(plan.event_ids), dict(plan.ticker_event_ids), plan.id,
        )
    news_by_session: dict[date, list[tuple[object, str, datetime]]] = {}
    for event, event_id in news_events or []:
        if event_id in portfolio.processed_news_event_ids:
            continue
        scheduled_open = next_session_open(event.event_datetime)
        news_by_session.setdefault(scheduled_open.astimezone(NEW_YORK).date(), []).append(
            (event, event_id, scheduled_open),
        )
    previous_rebalance = portfolio.last_rebalanced_at
    if previous_rebalance:
        previous_stamp = pd.Timestamp(previous_rebalance)
        previous_rebalance_date = (previous_stamp.tz_convert("UTC").tz_localize(None)
                                   if previous_stamp.tzinfo else previous_stamp).normalize()
        prior_indexes = [i for i, stamp in enumerate(session_dates) if stamp <= previous_rebalance_date]
        last_rebalance_index = prior_indexes[-1] if prior_indexes else max(0, first_index - 1)
    else:
        last_rebalance_index = None

    for index in range(first_index, len(session_dates)):
        session = session_dates[index]
        open_row = opens.loc[session]
        close_row = closes.loc[session]
        session_order_start = len(order_rows)
        plan = pending_targets.pop(session, None)
        todays_news = news_by_session.pop(session.date(), [])
        if plan or todays_news:
            target_weights = dict(plan[0]) if plan else _current_weights(portfolio)
            origins = {ticker: list(ids) for ticker, ids in (plan[4].items() if plan else [])}
            news_origins = _apply_news_targets(portfolio, target_weights, todays_news, repository)
            for ticker, ids in news_origins.items():
                origins[ticker] = list(dict.fromkeys([*origins.get(ticker, []), *ids]))
            for _, event_id, _ in todays_news:
                _remember_news_event(portfolio, event_id)
            if plan or origins:
                event_ids = list(dict.fromkeys([
                    *(plan[3] if plan else []),
                    *(event_id for ids in news_origins.values() for event_id in ids),
                ]))
                reason = plan[1] if plan else "news_sentiment"
                event_id = next((ids[0] for ids in origins.values() if ids), None)
                _execute_at_open(
                    portfolio, target_weights, open_row, order_rows, reason=reason,
                    filled_at=session, event_id=event_id, event_ids=event_ids,
                    ticker_event_ids=origins,
                )
                portfolio.last_rebalanced_at = _session_time(session, time(9, 30))
                portfolio.last_rebalance_trigger = reason
                last_rebalance_index = index
            if plan and plan[5]:
                repository.finish_pending_rebalance(
                    plan[5], executed_at=_session_time(session, time(9, 30)),
                )

        _mark_close(portfolio, close_row)
        benchmark_value = portfolio.initial_capital * float(benchmark.loc[session]) / float(portfolio.benchmark_initial_price)
        portfolio.benchmark_value = benchmark_value
        _record_session(portfolio, session, benchmark_value, order_rows[session_order_start:])
        processed_days += 1

        warmup_end = portfolio.config.rs_lookback_days - 1
        if index < max(first_index, warmup_end) or index == len(session_dates) - 1:
            if index == len(session_dates) - 1 and index >= warmup_end:
                reason = _signal_reason(portfolio, volumes, index, last_rebalance_index)
                if reason:
                    target = _target_weights(portfolio, closes.iloc[:index + 1], benchmark.loc[:session])
                    if target:
                        decision_at = _session_time(session, MARKET_CLOSE)
                        scheduled_open = next_session_open(decision_at)
                        repository.queue_rebalance(
                            portfolio_id=portfolio.id, event_id=None,
                            decision_at=decision_at,
                            scheduled_for=scheduled_open, reason=f"strategy:{reason}", target_weights=target,
                        )
            continue

        reason = _signal_reason(portfolio, volumes, index, last_rebalance_index)
        if reason:
            target = _target_weights(portfolio, closes.iloc[:index + 1], benchmark.loc[:session])
            if target:
                next_session = session_dates[index + 1]
                pending_targets[next_session] = (target, f"strategy:{reason}", None, [], {}, None)

    # Preserve signals dated after the last completed bar for the live opening-price worker.
    if news_by_session:
        latest = session_dates[-1]
        targets = _current_weights(portfolio)
        pending_origins: dict[str, list[str]] = {}
        for _, rows in sorted(news_by_session.items()):
            for event, event_id, scheduled_open in rows:
                event_origins = _apply_news_targets(portfolio, targets, [(event, event_id, scheduled_open)], repository)
                for ticker, ids in event_origins.items():
                    pending_origins[ticker] = list(dict.fromkeys([*pending_origins.get(ticker, []), *ids]))
                _remember_news_event(portfolio, event_id)
        pending_events = list(dict.fromkeys(event_id for ids in pending_origins.values() for event_id in ids))
        if pending_events:
            scheduled_open = min(
                row[2] for rows in news_by_session.values() for row in rows
            )
            repository.queue_rebalance(
                portfolio_id=portfolio.id,
                event_id=pending_events[0], event_ids=pending_events,
                decision_at=latest.to_pydatetime().replace(tzinfo=timezone.utc),
                scheduled_for=scheduled_open,
                reason="news_sentiment",
                target_weights=targets,
                ticker_event_ids=pending_origins,
            )

    if order_rows:
        repository.insert_orders(order_rows)
        portfolio.order_count += len(order_rows)
    if processed_days:
        portfolio.last_processed_session = session_dates[-1].date()
        portfolio.backtest_complete = True
        repository.save_portfolio(portfolio)
    elif not portfolio.backtest_complete and prior_day is not None:
        portfolio.last_processed_session = prior_day
        portfolio.backtest_complete = True
        repository.save_portfolio(portfolio)
    return portfolio, processed_days, len(order_rows)


def _current_weights(portfolio: Portfolio) -> dict[str, float]:
    return {row.ticker_id: row.weight for row in portfolio.positions if row.weight > 0}


def _remember_news_event(portfolio: Portfolio, event_id: str) -> None:
    if event_id not in portfolio.processed_news_event_ids:
        portfolio.processed_news_event_ids.append(event_id)
        portfolio.processed_news_event_ids = portfolio.processed_news_event_ids[-4096:]
    portfolio.last_news_event_id = event_id


def _apply_news_targets(portfolio: Portfolio, targets: dict[str, float], events: list[tuple[object, str, datetime]], repository) -> dict[str, list[str]]:
    origins: dict[str, list[str]] = {}
    for event, event_id, _ in events:
        if event.sentiment is None:
            continue
        direct = {ticker.ticker_id for ticker in event.relevant_tickers}
        for ticker in event.relevant_tickers:
            contribution = event.sentiment.score * event.sentiment.impact_score * ticker.relevance_score
            if abs(contribution) >= portfolio.config.sentiment_delta_threshold:
                step = min(portfolio.config.news_weight_step,
                           portfolio.config.max_position_weight * abs(contribution))
                if _shift_weight(targets, ticker.ticker_id, contribution, step,
                                 portfolio.config.max_position_weight):
                    origins.setdefault(ticker.ticker_id, []).append(event_id)
            graph = repository.get_ticker_graph(ticker.ticker_id)
            if graph is None:
                continue
            for neighbor, correlation in graph.correlations.items():
                if neighbor in direct:
                    continue
                propagated = contribution * correlation * GRAPH_PROPAGATION_SCALE
                if abs(propagated) >= portfolio.config.sentiment_delta_threshold:
                    step = min(portfolio.config.news_weight_step,
                               portfolio.config.max_position_weight * abs(propagated))
                    if _shift_weight(targets, neighbor, propagated, step,
                                     portfolio.config.max_position_weight):
                        origins.setdefault(neighbor, []).append(event_id)
    return {ticker: list(dict.fromkeys(ids)) for ticker, ids in origins.items()}


def _shift_weight(targets: dict[str, float], ticker: str, signal: float, step: float, maximum: float) -> bool:
    current = targets.get(ticker, 0.0)
    updated = min(maximum, current + step) if signal > 0 else max(0.0, current - step)
    if updated == current:
        return False
    targets[ticker] = updated
    return True


def _signal_reason(portfolio: Portfolio, volumes: pd.DataFrame, index: int,
                   last_rebalance_index: int | None) -> str | None:
    if last_rebalance_index is None:
        return "initial"
    if index - last_rebalance_index >= portfolio.config.rebalance_days:
        return "static_period"
    if index < 24 or not portfolio.positions:
        return None
    today = volumes.iloc[index]
    recent = volumes.iloc[index - 4:index + 1].mean()
    baseline = volumes.iloc[index - 24:index - 4].mean()
    held = {position.ticker_id for position in portfolio.positions}
    for ticker in held.intersection(recent.index):
        normal = float(baseline.get(ticker, 0.0))
        current = float(recent.get(ticker, 0.0))
        if normal > 0 and current / normal >= portfolio.config.volume_spike_ratio and pd.notna(today.get(ticker)):
            return "volume_spike"
    return None


def _target_weights(portfolio: Portfolio, closes: pd.DataFrame, benchmark: pd.Series) -> dict[str, float]:
    ranked = rank_residual_strength(
        closes, benchmark, lookback_days=portfolio.config.rs_lookback_days,
        candidate_count=portfolio.config.candidate_count, portfolio_size=portfolio.config.portfolio_size,
    )
    if not ranked:
        return {}
    return mean_variance_weights(
        closes,
        [ticker for ticker, _ in ranked],
        max_position_weight=portfolio.config.max_position_weight,
        lookback_days=portfolio.config.rs_lookback_days,
    )


def _execute_at_open(portfolio: Portfolio, target_weights: dict[str, float], open_row: pd.Series,
                     orders: list[TradeOrder], *, reason: str, filled_at: pd.Timestamp,
                     event_id: str | None = None, event_ids: list[str] | None = None,
                     ticker_event_ids: dict[str, list[str]] | None = None) -> None:
    prices = {str(key): float(value) for key, value in open_row.items() if pd.notna(value) and float(value) > 0}
    equity = portfolio.cash + sum(
        position.shares * prices.get(position.ticker_id, position.last_price)
        for position in portfolio.positions
    )
    desired = {
        ticker: int(weight * equity / prices[ticker])
        for ticker, weight in target_weights.items() if ticker in prices
    }
    target_total = sum(max(0.0, float(weight)) for weight in target_weights.values())
    if reason == "news_sentiment" and target_total > 1.0:
        desired = {
            ticker: int((max(0.0, float(weight)) / target_total) * equity / prices[ticker])
            for ticker, weight in target_weights.items() if ticker in prices
        }
    held = {position.ticker_id: position.shares for position in portfolio.positions}
    ticker_event_ids = ticker_event_ids or {}
    def order_origin(ticker: str) -> tuple[str, list[str]]:
        ids = ticker_event_ids.get(ticker, [])
        if not ids and reason == "news_sentiment":
            ids = event_ids or ([event_id] if event_id else [])
        if not ids and not ticker_event_ids and reason == "news_sentiment":
            ids = event_ids or ([event_id] if event_id else [])
        return ("news_sentiment" if ids else reason), ids

    for ticker, shares in held.items():
        quantity = max(0, shares - desired.get(ticker, 0))
        if quantity:
            if ticker in prices:
                order_reason, order_event_ids = order_origin(ticker)
                _fill(portfolio, orders, ticker, OrderSide.SELL, quantity, prices[ticker], order_reason,
                      filled_at, order_event_ids)
    for ticker, shares in desired.items():
        position = next((row for row in portfolio.positions if row.ticker_id == ticker), None)
        quantity = max(0, shares - (position.shares if position else 0))
        if not quantity:
            continue
        price = prices[ticker]
        affordable = int(portfolio.cash / (price * (1.0 + portfolio.config.transaction_cost)))
        quantity = min(quantity, affordable)
        if quantity:
            order_reason, order_event_ids = order_origin(ticker)
            _fill(portfolio, orders, ticker, OrderSide.BUY, quantity, price, order_reason,
                  filled_at, order_event_ids)


def _fill(portfolio: Portfolio, orders: list[TradeOrder], ticker: str, side: OrderSide, quantity: int,
          price: float, reason: str, filled_at: pd.Timestamp, event_ids: list[str]) -> None:
    gross = price * quantity
    fee = gross * portfolio.config.transaction_cost
    position = next((row for row in portfolio.positions if row.ticker_id == ticker), None)
    if side == OrderSide.BUY:
        previous = position.shares if position else 0
        average = ((position.average_cost * previous + gross) / (previous + quantity)) if previous else price
        if position:
            position.shares += quantity
            position.average_cost = average
        else:
            portfolio.positions.append(PortfolioPosition(
                ticker_id=ticker, shares=quantity, average_cost=price, last_price=price,
            ))
        portfolio.cash -= gross + fee
        net_cash = -(gross + fee)
    else:
        if position is None:
            return
        portfolio.total_realized_pnl += (price - position.average_cost) * quantity - fee
        position.shares -= quantity
        portfolio.cash += gross - fee
        net_cash = gross - fee
        if position.shares == 0:
            portfolio.positions.remove(position)
    orders.append(TradeOrder(
        _id=str(ObjectId()), portfolio_id=portfolio.id, ticker_id=ticker, side=side,
        quantity=quantity, price=price, gross_value=gross, transaction_cost=fee,
        net_cash_change=net_cash, event_id=event_ids[0] if event_ids else None,
        event_ids=event_ids, reason=reason,
        created_at=_session_time(filled_at, time(9, 30)),
    ))


def _mark_close(portfolio: Portfolio, close_row: pd.Series) -> None:
    invested = 0.0
    unrealized = 0.0
    for position in portfolio.positions:
        close = close_row.get(position.ticker_id)
        if close is not None and pd.notna(close) and float(close) > 0:
            position.last_price = float(close)
        position.market_value = position.shares * position.last_price
        position.unrealized_pnl = (position.last_price - position.average_cost) * position.shares
        position.weight = 0.0
        invested += position.market_value
        unrealized += position.unrealized_pnl
    portfolio.portfolio_value = portfolio.cash + invested
    portfolio.total_unrealized_pnl = unrealized
    for position in portfolio.positions:
        position.weight = position.market_value / portfolio.portfolio_value if portfolio.portfolio_value else 0.0


def _record_session(portfolio: Portfolio, session: pd.Timestamp, benchmark_value: float,
                    session_orders: list[TradeOrder] | None = None) -> None:
    total = portfolio.portfolio_value
    previous = portfolio.value_history[-1].total_value if portfolio.value_history else portfolio.initial_capital
    daily_return = total / previous - 1.0 if previous else 0.0
    historical = [point.total_value for point in portfolio.value_history]
    returns = np.diff(historical + [total]) / np.maximum(historical, 1e-12) if historical else np.array([])
    volatility = float(np.std(returns, ddof=1) * np.sqrt(252)) if len(returns) > 1 else 0.0
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.mean(returns) / std * np.sqrt(252)) if std > 0 else 0.0
    peak = max([portfolio.initial_capital, *(point.total_value for point in portfolio.value_history), total])
    stamp = _session_time(session, time(16, 0))
    portfolio.peak_value = max(portfolio.peak_value, peak)
    portfolio.daily_metrics.append(PortfolioDailyMetrics(
        date=stamp, portfolio_value=total,
        position_weights={position.ticker_id: position.weight for position in portfolio.positions if position.shares > 0},
        daily_pnl=total - previous, daily_return=daily_return,
        cumulative_pnl=total - portfolio.initial_capital,
        cumulative_return=total / portfolio.initial_capital - 1.0,
        drawdown=min(0.0, total / peak - 1.0), annualized_volatility=volatility,
        sharpe_ratio=sharpe, realized_pnl=portfolio.total_realized_pnl,
        unrealized_pnl=portfolio.total_unrealized_pnl,
        turnover=(sum(order.gross_value for order in session_orders or []) / previous if previous else 0.0),
        transaction_cost=sum(order.transaction_cost for order in session_orders or []),
        benchmark_return=(benchmark_value / portfolio.value_history[-1].benchmark_value - 1.0)
        if portfolio.value_history and portfolio.value_history[-1].benchmark_value else None,
    ))
    portfolio.value_history.append(PortfolioValuePoint(
        timestamp=stamp, total_value=total, cash=portfolio.cash,
        invested_value=total - portfolio.cash, benchmark_value=benchmark_value,
    ))
    portfolio.daily_metrics = portfolio.daily_metrics[-3650:]
    portfolio.value_history = portfolio.value_history[-3650:]
