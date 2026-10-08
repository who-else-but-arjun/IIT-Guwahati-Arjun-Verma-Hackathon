import { useMemo, useState } from "react";
import { LineChart } from "../components/LineChart";
import { WeightHistoryChart } from "../components/WeightHistoryChart";
import { NewsPurchaseStackedArea } from "../components/NewsPurchaseStackedArea";
import { DataNotice, PageHeading, Skeleton, TickerMark } from "../components/AppShell";
import { PortfolioMarkerDrawer } from "../components/DetailsDrawers";
import { eventId } from "../services/api";
import { changeClass, dateTime, formatReason, impactScore, money, number, percent, tickerOf } from "../utils/format";

const strategyName = (p) => p.news_enabled ? "News + Normal Rebalancing" : "Normal Rebalancing";
const dateKey = (value) => value ? new Date(value).toISOString().slice(0, 10) : "";
const metricValue = (metric, mode) => mode === "value" ? metric.portfolio_value : mode === "return" ? Number(metric.cumulative_return || 0) * 100 : Number(metric.drawdown || 0) * 100;
const sparkPath = (values = []) => {
  if (values.length < 2) return "";
  const low = Math.min(...values), span = Math.max(...values) - low || 1;
  return values.map((value, index) => `${index ? "L" : "M"}${(index * 54 / (values.length - 1)).toFixed(1)},${(19 - (value - low) * 16 / span).toFixed(1)}`).join(" ");
};
const pendingTradePreview = (plan, portfolio, prices) => {
  const positions = Array.isArray(portfolio?.positions) ? portfolio.positions : [];
  const positionByTicker = new Map(positions.map((position) => [tickerOf(position), position]));
  const targets = Object.fromEntries(Object.entries(plan?.target_weights || {}).map(([ticker, weight]) => [ticker.toUpperCase(), Number(weight) || 0]));
  const targetTotal = Object.values(targets).reduce((sum, weight) => sum + weight, 0);
  if (String(plan?.reason || "").toLowerCase().includes("news") && targetTotal > 1) {
    for (const ticker of Object.keys(targets)) targets[ticker] /= targetTotal;
  }
  const tickers = [...new Set([...positionByTicker.keys(), ...Object.keys(targets)])];
  const marks = new Map(tickers.map((ticker) => [ticker, Number(prices?.[ticker]?.price || positionByTicker.get(ticker)?.last_price) || 0]));
  const portfolioValue = Math.max(0, Number(portfolio?.cash) || 0) + positions.reduce((sum, position) => {
    const ticker = tickerOf(position);
    return sum + (Number(position.shares) || 0) * (marks.get(ticker) || 0);
  }, 0);
  return tickers.map((ticker) => {
    const price = marks.get(ticker) || 0;
    const currentShares = Number(positionByTicker.get(ticker)?.shares) || 0;
    const desiredShares = price > 0 ? Math.floor((targets[ticker] || 0) * portfolioValue / price) : currentShares;
    const delta = desiredShares - currentShares;
    return { ticker, side: delta > 0 ? "buy" : "sell", shares: Math.abs(delta), price, value: Math.abs(delta) * price };
  }).filter((trade) => trade.shares > 0).sort((a, b) => (a.side === "sell" ? 0 : 1) - (b.side === "sell" ? 0 : 1) || a.ticker.localeCompare(b.ticker));
};

export function PortfolioPage({ portfolios, portfolioOrders = [], loading, quoteLoading = false, error, refresh, onTicker, onOrders, onRebalance, pending = {}, rebalances = {}, prices = {}, events = [], onEvent, tickers = [] }) {
  const [selectedId, setSelectedId] = useState("");
  const [tab, setTab] = useState("holdings");
  const [range, setRange] = useState("3m");
  const [mode, setMode] = useState("value");
  const [compareBoth, setCompareBoth] = useState(false);
  const [sort, setSort] = useState({ key: "market_value", direction: -1 });
  const [rebalanceBusy, setRebalanceBusy] = useState(false);
  const [activeMarker, setActiveMarker] = useState(null);
  const [compositionView, setCompositionView] = useState("weights");
  const available = Array.isArray(portfolios) ? portfolios.filter(Boolean) : [];
  const selected = available.find((p) => p.id === selectedId) || available.find((p) => p.news_enabled) || available[0];
  const series = useMemo(() => selected ? (compareBoth ? available : [selected]).map((portfolio) => {
    const history = mode === "value" ? portfolio.value_history : portfolio.daily_metrics;
    const normalized = (Array.isArray(history) ? history : []).map((item) => ({ timestamp: item.timestamp || item.date, value: mode === "value" ? item.total_value : metricValue(item, mode) })).filter((x) => x.timestamp && Number.isFinite(Number(x.value)));
    const days = range === "1m" ? 31 : range === "3m" ? 93 : range === "1y" ? 366 : Infinity;
    const cutoff = Date.now() - days * 86400000;
    return { name: strategyName(portfolio), color: portfolio.news_enabled ? "#df3038" : "#17191e", data: normalized.filter((point) => new Date(point.timestamp).getTime() >= cutoff) };
  }) : [], [available, selected, mode, range, compareBoth]);
  const positions = Array.isArray(selected?.positions) ? selected.positions : [];
  const rows = [...positions].sort((a, b) => { const left = a[sort.key] ?? 0, right = b[sort.key] ?? 0; return (typeof left === "string" ? left.localeCompare(right) : left - right) * sort.direction; });
  const changeSort = (key) => setSort((current) => ({ key, direction: current.key === key ? -current.direction : -1 }));
  const pendingPlans = Array.isArray(pending?.[selected?.id]) ? pending[selected.id] : [];
  const rebalanceHistory = Array.isArray(rebalances?.[selected?.id]) ? rebalances[selected.id] : [];
  const chartSeries = compareBoth ? available : selected ? [selected] : [];
  const seriesHistory = new Map(chartSeries.map((portfolio) => [portfolio.id, (Array.isArray(mode === "value" ? portfolio.value_history : portfolio.daily_metrics) ? (mode === "value" ? portfolio.value_history : portfolio.daily_metrics) : []).map((item) => ({ timestamp: item.timestamp || item.date, value: mode === "value" ? item.total_value : metricValue(item, mode) })).filter((point) => point.timestamp && Number.isFinite(Number(point.value))).filter((point) => {
    const days = range === "1m" ? 31 : range === "3m" ? 93 : range === "1y" ? 366 : Infinity;
    return new Date(point.timestamp).getTime() >= Date.now() - days * 86400000;
  })]));
  const markerForSeries = (history, timestamp) => {
    const at = new Date(timestamp).getTime();
    if (!history?.length || !Number.isFinite(at)) return null;
    const start = new Date(history[0].timestamp).getTime(), end = new Date(history.at(-1).timestamp).getTime();
    if (at < start || at > end) return null;
    return history.reduce((best, point, index) => Math.abs(new Date(point.timestamp).getTime() - at) < Math.abs(new Date(history[best].timestamp).getTime() - at) ? index : best, 0);
  };
  const safeOrders = Array.isArray(portfolioOrders) ? portfolioOrders : [];
  const ordersForPlan = (plan) => {
    const ids = new Set([...(plan.event_ids || []), ...Object.values(plan.ticker_event_ids || {}).flat()]);
    const planTime = new Date(plan.executed_at || plan.scheduled_for || plan.decision_at || plan.created_at).getTime();
    return safeOrders.filter((order) => {
      if (order.portfolio_id !== plan.portfolio_id) return false;
      const orderIds = [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])];
      if (ids.size && orderIds.some((id) => ids.has(id))) return true;
      const orderTime = new Date(order.executed_at || order.created_at).getTime();
      return Number.isFinite(planTime) && Number.isFinite(orderTime) && Math.abs(orderTime - planTime) <= 36 * 60 * 60 * 1000 && String(order.reason || "").toLowerCase() === String(plan.reason || "").toLowerCase();
    });
  };
  const rebalanceGroups = new Map();
  const visiblePortfolioIds = new Set(chartSeries.map((portfolio) => portfolio.id));
  for (const order of safeOrders) {
    if (!visiblePortfolioIds.has(order.portfolio_id) || !order.reason || order.reason === "manual") continue;
    const portfolio = chartSeries.find((item) => item.id === order.portfolio_id), history = seriesHistory.get(order.portfolio_id);
    const timestamp = order.executed_at || order.created_at, index = markerForSeries(history, timestamp);
    if (index == null) continue;
    const eventIds = [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])];
    const reason = String(order.reason).toLowerCase();
    const triggerKind = portfolio?.news_enabled && (reason.includes("news") || eventIds.length) ? "news-rebalance" : reason.includes("volume") || reason.includes("spike") ? "volume-spike" : "scheduled-rebalance";
    // The portfolio history is daily; group every trade on the same plotted day
    // and trigger type into one marker so several executions do not stack up.
    const key = `${order.portfolio_id}|${index}|${triggerKind}`;
    const current = rebalanceGroups.get(key) || { timestamp: history[index].timestamp, index, seriesName: strategyName(portfolio), portfolio_id: portfolio.id, triggerKind, reasons: new Set(), orders: [], plans: [], eventIds: new Set() };
    current.orders.push(order); current.reasons.add(order.reason); for (const id of eventIds) current.eventIds.add(id);
    rebalanceGroups.set(key, current);
  }
  for (const portfolio of chartSeries) {
    const history = seriesHistory.get(portfolio.id);
    for (const plan of (rebalances?.[portfolio.id] || [])) {
      if (plan.status === "cancelled") continue;
      const timestamp = plan.executed_at || plan.scheduled_for || plan.decision_at || plan.created_at;
      const index = markerForSeries(history, timestamp);
      if (index == null) continue;
      const eventIds = [...new Set([...(plan.event_ids || []), ...Object.values(plan.ticker_event_ids || {}).flat()])];
      const reason = String(plan.reason || "scheduled").toLowerCase();
      const triggerKind = portfolio.news_enabled && (reason.includes("news") || eventIds.length) ? "news-rebalance" : reason.includes("volume") || reason.includes("spike") ? "volume-spike" : "scheduled-rebalance";
      const key = `${portfolio.id}|${index}|${triggerKind}`;
      const current = rebalanceGroups.get(key) || { timestamp: history[index].timestamp, index, seriesName: strategyName(portfolio), portfolio_id: portfolio.id, triggerKind, reasons: new Set(), orders: [], plans: [], eventIds: new Set() };
      current.plans.push(plan); current.reasons.add(plan.reason || "scheduled");
      for (const id of eventIds) current.eventIds.add(id);
      rebalanceGroups.set(key, current);
    }
  }
  const rebalanceMarkers = [...rebalanceGroups].map(([id, row]) => {
    const linkedEvents = (Array.isArray(events) ? events : []).filter((item) => row.eventIds.has(eventId(item)));
    const triggerKind = row.triggerKind;
    const reason = [...row.reasons].join(", ");
    return { id, index: row.index, timestamp: row.timestamp, seriesName: row.seriesName, portfolio_id: row.portfolio_id, eventIds: [...row.eventIds], kind: "rebalance", triggerKind, events: linkedEvents, orders: row.orders, plan: row.plans.at(-1) || null, plans: row.plans, reason, offset: triggerKind === "news-rebalance" ? -5 : 5, label: `${formatReason(reason)} · ${row.orders.length} trade${row.orders.length === 1 ? "" : "s"}` };
  });
  // Older execution records don't carry a pending-plan ID. Associate them with
  // the plotted portfolio session so a plan marker does not misleadingly say 0 trades.
  const rebalanceMarkersWithOrders = rebalanceMarkers.map((marker) => {
    if (marker.orders.length) return marker;
    const history = seriesHistory.get(marker.portfolio_id);
    const sameSession = safeOrders.filter((order) => {
      if (order.portfolio_id !== marker.portfolio_id) return false;
      const stamp = order.executed_at || order.created_at;
      const orderIndex = markerForSeries(history, stamp);
      const withinExecutionWindow = Math.abs(new Date(stamp).getTime() - new Date(marker.timestamp).getTime()) <= 36 * 60 * 60 * 1000;
      return orderIndex === marker.index || withinExecutionWindow;
    });
    const sameTrigger = sameSession.filter((order) => {
      const reason = String(order.reason || "").toLowerCase();
      const ids = [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])];
      const kind = selected?.news_enabled && (reason.includes("news") || ids.length) ? "news-rebalance" : reason.includes("volume") || reason.includes("spike") ? "volume-spike" : "scheduled-rebalance";
      return kind === marker.triggerKind;
    });
    const orders = sameTrigger.length ? sameTrigger : sameSession;
    return { ...marker, orders, label: `${formatReason(marker.reason)} · ${orders.length} trade${orders.length === 1 ? "" : "s"}` };
  });
  const newsRebalanceMarkers = rebalanceMarkersWithOrders.filter((marker) => marker.triggerKind === "news-rebalance");
  const volumeRebalanceMarkers = rebalanceMarkersWithOrders.filter((marker) => marker.triggerKind !== "news-rebalance");
  const allChartMarkers = rebalanceMarkersWithOrders;
  const triggerRebalance = async () => { setRebalanceBusy(true); try { await onRebalance(selected.id); } finally { setRebalanceBusy(false); } };
  const chartRange = [ ["1m", "1M"], ["3m", "3M"], ["1y", "1Y"], ["all", "ALL"] ];
  return <>
    <PageHeading kicker="PAPER PORTFOLIOS" title="Portfolio" description="Switch strategies to review holdings, historical performance, and rebalance activity." actions={<><span className="paper-pill">PAPER TRADING</span><button className="button-secondary" onClick={onOrders}>Place an order <span>↗</span></button></>} />
    <div className="strategy-switch" role="tablist" aria-label="Portfolio strategy">{available.map((portfolio) => <button role="tab" aria-selected={portfolio.id === (selected?.id || "")} key={portfolio.id} className={portfolio.id === selected?.id ? "active" : ""} onClick={() => { setSelectedId(portfolio.id); setActiveMarker(null); }}><span className="strategy-dot"/>{strategyName(portfolio)}</button>)}</div>
    <DataNotice skeleton="chart" loading={loading && !available.length} error={error && !available.length ? error : ""} onRetry={refresh} empty={!available.length ? "" : null}>
      {selected && <>
        <section className="panel chart-panel"><div className="panel-heading"><div><div className="section-kicker">PERFORMANCE HISTORY</div><h2>{compareBoth ? "Portfolio performance comparison" : strategyName(selected)}</h2><p>Red dots mark news-driven rebalances; dark dots mark volume or scheduled rebalances. Select a dot for its full trade and decision details.</p></div><div className="chart-controls"><button className={`button-secondary compare-toggle ${compareBoth ? "active" : ""}`} onClick={() => setCompareBoth((value) => !value)}>{compareBoth ? "Show one portfolio" : "Compare both portfolios"}</button><div className="segmented">{[["value", "Value"], ["return", "Return"], ["drawdown", "Drawdown"]].map(([v, label]) => <button className={mode === v ? "active" : ""} onClick={() => setMode(v)} key={v}>{label}</button>)}</div><div className="segmented compact">{chartRange.map(([v, label]) => <button className={range === v ? "active" : ""} onClick={() => setRange(v)} key={v}>{label}</button>)}</div></div></div><div className="chart-legend">{series.map((line) => <span key={line.name}><i style={{ background: line.color }}/>{line.name}</span>)}{newsRebalanceMarkers.length > 0 && <span><i className="event-legend-dot"/>News-driven rebalance</span>}{volumeRebalanceMarkers.length > 0 && <span><i className="rebalance-legend-dot"/>Volume / scheduled rebalance</span>}</div><LineChart series={series} mode={mode === "value" ? "value" : "percent"} dateRange={range} currency={selected.currency} markers={allChartMarkers} onMarker={setActiveMarker} height={294}/></section>
        <section className="panel weight-history-panel"><div className="panel-heading"><div><div className="section-kicker">PORTFOLIO COMPOSITION</div><h2>{compositionView === "weights" ? "Portfolio weight composition" : "Shares purchased on news"}</h2><p>{compositionView === "weights" ? "Stacked areas show each holding’s share of total portfolio value. Select a rebalance marker to review its orders." : "See how news-linked purchases build each holding over time. Hover a stock area and open the linked news event."}</p></div><div className="segmented composition-view-tabs" role="tablist" aria-label="Portfolio composition chart">{[["weights", "Weight composition"], ["news-trades", "News purchases"]].map(([view, label]) => <button key={view} type="button" role="tab" aria-selected={compositionView === view} className={compositionView === view ? "active" : ""} onClick={() => setCompositionView(view)}>{label}</button>)}</div></div>{compositionView === "weights" ? <WeightHistoryChart metrics={selected.daily_metrics} height={330} tickers={tickers} positions={positions} portfolios={available} activePortfolioId={selected.id} newsEnabled={selected.news_enabled} orders={safeOrders.filter((order) => order.portfolio_id === selected.id)} rebalances={rebalanceHistory} events={events} onEvent={onEvent} onMarker={setActiveMarker} onPortfolioChange={(id) => { setSelectedId(id); setActiveMarker(null); }}/>: <NewsPurchaseStackedArea orders={safeOrders.filter((order) => order.portfolio_id === selected.id)} events={events} tickers={tickers} onEvent={onEvent}/>}</section>
        <section className="panel portfolio-content"><div className="portfolio-tabs"><div className="content-tabs">{[["holdings", "Holdings"], ["performance", "Analysis"], ["activity", "Activity"], ["strategy", "Strategy"]].map(([v, label]) => <button key={v} className={tab === v ? "active" : ""} onClick={() => setTab(v)}>{label}</button>)}</div></div>
          {tab === "holdings" && <><div className="table-heading"><div><h2>Current holdings</h2><p>{positions.length} active positions <span>·</span> Click a stock to see its trade history</p></div><button className="text-button" onClick={onOrders}>View order history ↗</button></div>{rows.length ? <div className="table-scroll"><table className="data-table"><thead><tr>{[["ticker_id", "Stock"], ["last_price", "Price"], ["day_change", "Day change"], ["shares", "Shares"], ["weight", "Weight"], ["market_value", "Market value"], ["average_cost", "Avg. cost"], ["unrealized_pnl", "Unrealized P&L"]].map(([key, label]) => <th className={key === "ticker_id" ? "" : "numeric"} key={key}><button onClick={() => key !== "day_change" && changeSort(key)}>{label}{sort.key === key ? sort.direction > 0 ? " ↑" : " ↓" : ""}</button></th>)}</tr></thead><tbody>{rows.map((position) => { const symbol = tickerOf(position), quote = prices[symbol]; return <tr key={symbol} onClick={() => onTicker(symbol)} tabIndex="0" onKeyDown={(e) => e.key === "Enter" && onTicker(symbol)}><td><span className="ticker-cell"><TickerMark symbol={symbol} tickers={tickers}/><b>{symbol}</b>{quote?.sparkline?.length > 1 && <svg className={`holding-spark ${quote.change < 0 ? "dn" : "up"}`} viewBox="0 0 54 20" aria-label={`${symbol} recent price trend`}><path d={sparkPath(quote.sparkline)}/></svg>}</span></td><td className="numeric">{quote?.price != null ? money(quote.price, selected.currency) : position.last_price != null ? money(position.last_price, selected.currency) : quoteLoading ? <Skeleton variant="inline" width="48px"/> : "—"}</td><td className={`numeric ${changeClass(quote?.change)}`}>{quote?.change == null ? quoteLoading ? <Skeleton variant="inline" width="38px"/> : "—" : percent(quote.change, 2, false)}</td><td className="numeric">{number(position.shares, 0)}</td><td className="numeric">{percent(position.weight, 2)}</td><td className="numeric">{money(position.market_value, selected.currency)}</td><td className="numeric">{money(position.average_cost, selected.currency)}</td><td className={`numeric ${changeClass(position.unrealized_pnl)}`}>{money(position.unrealized_pnl, selected.currency)}</td></tr>; })}</tbody></table></div> : <div className="table-empty">No active positions in this portfolio.</div>}</>}
          {tab === "performance" && <PerformancePanel portfolio={selected}/>}
          {tab === "activity" && <div className="activity-content"><div className="table-heading"><div><h2>Rebalance activity</h2><p>Portfolio decisions and next-session execution plans.</p></div><button className="button-secondary" disabled={rebalanceBusy || pendingPlans.length > 0} onClick={triggerRebalance}>{rebalanceBusy ? "Scheduling…" : "Run normal rebalance"}</button></div>{pendingPlans.length ? <div className="pending-callout"><i className="pending-dot"/><div className="pending-plan-content"><b>{pendingPlans.length} rebalance plan{pendingPlans.length > 1 ? "s" : ""} pending</b>{pendingPlans.map((plan) => { const trades = pendingTradePreview(plan, selected, prices); return <section className="pending-plan-card" key={plan.id}><header><b>{formatReason(plan.reason)}</b><span>Scheduled {dateTime(plan.scheduled_for)}</span></header>{trades.length ? <><div className="pending-order-list">{trades.map((trade) => <div className="pending-order-row" key={`${plan.id}-${trade.ticker}`}><span className="ticker-cell"><TickerMark symbol={trade.ticker} tickers={tickers}/><b>{trade.ticker}</b></span><span className={`side-badge ${trade.side}`}>{trade.side}</span><strong>{number(trade.shares, 0)} shares</strong><span className="pending-order-value">{trade.price ? `~${money(trade.value, selected.currency)}` : "Price unavailable"}</span></div>)}</div><small className="pending-plan-note">Estimated quantities at current reference prices; final orders may change at execution.</small></> : <p className="pending-plan-empty">No share changes are projected from this plan.</p>}</section>; })}</div></div> : <p className="empty-note">No pending rebalance plans.</p>}{selected.last_rebalanced_at && <div className="activity-item"><span className="activity-glyph">↻</span><div><b>Last rebalance</b><p>{formatReason(selected.last_rebalance_trigger || "Strategy rebalance")} · {dateTime(selected.last_rebalanced_at)}</p></div></div>}{rebalanceHistory.length > 0 && <div className="activity-history"><h3>Recent execution plans</h3>{rebalanceHistory.slice(0, 10).map((plan) => { const trades = ordersForPlan(plan); const label = plan.status === "filled" ? `Completed · ${trades.length} trade${trades.length === 1 ? "" : "s"}` : "Pending"; return <div className="activity-item" key={plan.id}><span className="activity-glyph">{plan.status === "filled" ? "✓" : "◷"}</span><div><b>{formatReason(plan.reason)} · {label}</b><p>{plan.status === "filled" ? `Executed ${dateTime(plan.executed_at || plan.scheduled_for)}` : `Scheduled ${dateTime(plan.scheduled_for)}`} · {trades.length} recorded trade{trades.length === 1 ? "" : "s"} · {(plan.event_ids || []).length} linked news events</p></div></div>; })}</div>}<button className="text-button" onClick={onOrders}>Review portfolio orders ↗</button></div>}
          {tab === "strategy" && <StrategyPanel portfolio={selected}/>}
        </section>
      </>}
    </DataNotice>
    {activeMarker && <PortfolioMarkerDrawer marker={activeMarker} portfolios={available} events={events} currency={selected?.currency} onClose={() => setActiveMarker(null)} onEvent={(event) => { setActiveMarker(null); onEvent?.(event); }} onTicker={onTicker}/>}
  </>;
}

function PerformancePanel({ portfolio }) {
  const metrics = portfolio.daily_metrics || [];
  const latest = metrics.at(-1);
  const cards = [["Realized P&L", latest?.realized_pnl ?? portfolio.total_realized_pnl, "cash"], ["Unrealized P&L", latest?.unrealized_pnl ?? portfolio.total_unrealized_pnl, "cash"], ["Annualized volatility", latest?.annualized_volatility, "ratio"], ["Sharpe ratio", latest?.sharpe_ratio, "plain"], ["Maximum current drawdown", latest?.drawdown, "ratio"], ["Turnover", latest?.turnover, "ratio"], ["Transaction cost", latest?.transaction_cost, "cash"], ["Benchmark return", latest?.benchmark_return, "ratio"]];
  return <div className="analysis-content"><div className="table-heading"><div><h2>Portfolio analysis</h2><p>Latest stored portfolio metrics. Values depend on the available history.</p></div></div><div className="metric-grid">{cards.map(([label, value, type]) => <div className="metric-card" key={label}><span>{label}</span><b>{value == null ? "—" : type === "cash" ? money(value, portfolio.currency) : type === "ratio" ? percent(value) : number(value, 2)}</b></div>)}</div><div className="table-scroll"><table className="data-table"><thead><tr><th>Date</th><th className="numeric">Value</th><th className="numeric">Daily P&L</th><th className="numeric">Cumulative return</th><th className="numeric">Drawdown</th><th className="numeric">Costs</th></tr></thead><tbody>{[...metrics].slice(-30).reverse().map((m, i) => <tr key={`${m.date}-${i}`}><td>{dateTime(m.date)}</td><td className="numeric">{money(m.portfolio_value, portfolio.currency)}</td><td className={`numeric ${changeClass(m.daily_pnl)}`}>{money(m.daily_pnl, portfolio.currency)}</td><td className={`numeric ${changeClass(m.cumulative_return)}`}>{percent(m.cumulative_return)}</td><td className="numeric negative">{percent(m.drawdown)}</td><td className="numeric">{money(m.transaction_cost, portfolio.currency)}</td></tr>)}</tbody></table></div></div>;
}

function StrategyPanel({ portfolio }) {
  const config = portfolio.config || {};
  const rows = [["Benchmark", config.benchmark_ticker], ["Rebalance interval", `${config.rebalance_days ?? "—"} days`], ["Relative-strength lookback", `${config.rs_lookback_days ?? "—"} days`], ["Candidate universe size", config.candidate_count], ["Target portfolio size", config.portfolio_size], ["Volume spike trigger", config.volume_spike_ratio ? `${number(config.volume_spike_ratio)}×` : "—"], ["Minimum news impact score", portfolio.news_enabled ? impactScore(config.min_news_impact_score ?? 0.65) : "Not applied"], ["News sentiment threshold", portfolio.news_enabled ? number(config.sentiment_delta_threshold) : "Not applied"], ["News target-weight step", portfolio.news_enabled ? percent(config.news_weight_step) : "Not applied"], ["Maximum position weight", percent(config.max_position_weight)], ["Transaction cost per side", percent(config.transaction_cost)]];
  return <div className="strategy-content"><div className="table-heading"><div><h2>Strategy configuration</h2><p>{strategyName(portfolio)} · {portfolio.status} · {portfolio.backtest_complete ? "Historical replay complete" : "Replay incomplete"}</p></div></div><div className="strategy-grid">{rows.map(([label, value]) => <div className="strategy-row" key={label}><span>{label}</span><b>{value ?? "—"}</b></div>)}</div><div className="strategy-footnote">These settings are read from the selected portfolio. Market prices and paper orders may use delayed or historical data.</div></div>;
}
