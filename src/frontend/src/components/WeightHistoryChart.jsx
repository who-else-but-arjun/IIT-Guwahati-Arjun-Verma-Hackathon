import { useEffect, useMemo, useState } from "react";
import { eventId } from "../services/api";
import { number } from "../utils/format";
import { TickerMark } from "./AppShell";

const colors = ["#df3038", "#167b60", "#3768a5", "#b77b20", "#7b55a3", "#238997", "#b34f7d", "#6d747e"];
const ranges = [["1m", "1M"], ["3m", "3M"], ["1y", "1Y"], ["max", "ALL"]];

export function WeightHistoryChart({ metrics = [], symbol, orders = [], rebalances = [], events = [], onEvent, onMarker, height = 220, tickers = [], positions = [], portfolios = [], activePortfolioId, newsEnabled = false, onPortfolioChange }) {
  const [range, setRange] = useState("3m");
  const [selectedTickers, setSelectedTickers] = useState("top8");
  const [search, setSearch] = useState("");
  useEffect(() => { setSelectedTickers("top8"); }, [metrics, symbol]);

  // Keep the latest non-empty snapshot for each market date. Legacy databases can
  // contain duplicate daily rows; plotting both makes a false extra data point.
  const allRows = useMemo(() => {
    const byDate = new Map();
    for (const row of metrics || []) {
      if (!row?.date || !row.position_weights || !Object.keys(row.position_weights).length) continue;
      const key = new Date(row.date).toISOString().slice(0, 10);
      byDate.set(key, row);
    }
    return [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, row]) => row);
  }, [metrics]);
  const availableTickers = useMemo(() => symbol ? [String(symbol).toUpperCase()] : [...new Set(allRows.flatMap((row) => Object.keys(row.position_weights || {})))].sort((a, b) => {
    const latest = allRows.at(-1)?.position_weights || {};
    return (Number(latest[b]) || 0) - (Number(latest[a]) || 0) || a.localeCompare(b);
  }), [allRows, symbol]);
  const rows = useMemo(() => {
    if (range === "max" || !allRows.length) return allRows;
    const days = range === "1m" ? 31 : range === "3m" ? 93 : 366;
    const cutoff = new Date(allRows.at(-1).date).getTime() - days * 86400000;
    return allRows.filter((row) => new Date(row.date).getTime() >= cutoff);
  }, [allRows, range]);
  const defaultTickers = availableTickers.slice(0, 8);
  const visibleTickers = selectedTickers === "top8" ? defaultTickers : selectedTickers === null ? availableTickers : availableTickers.filter((ticker) => selectedTickers.includes(ticker));
  const companyByTicker = useMemo(() => new Map((tickers || []).map((item) => {
    const ticker = String(item.ticker_name?.ticker_id || item.ticker_id || "").toUpperCase();
    return [ticker, item.ticker_name?.company_name || item.company_name || ticker];
  })), [tickers]);
  const sharesByTicker = useMemo(() => new Map((positions || []).map((position) => [String(position.ticker_id || position.ticker || "").toUpperCase(), Number(position.shares) || 0])), [positions]);
  const filteredOptions = availableTickers.filter((ticker) => `${ticker} ${companyByTicker.get(ticker) || ""}`.toLowerCase().includes(search.toLowerCase()));
  const series = visibleTickers.map((ticker, index) => ({
    name: ticker,
    color: colors[index % colors.length],
    data: rows.map((row) => ({ timestamp: row.date, value: (Number(row.position_weights?.[ticker]) || 0) * 100 })),
  }));
  const otherTickers = availableTickers.filter((ticker) => !visibleTickers.includes(ticker));
  const stackSeries = [...series];
  if (otherTickers.length && visibleTickers.length) stackSeries.push({
    name: "Other holdings",
    color: "#89909a",
    data: rows.map((row) => ({ timestamp: row.date, value: otherTickers.reduce((sum, ticker) => sum + (Number(row.position_weights?.[ticker]) || 0) * 100, 0) })),
  });

  const linkedById = new Map((events || []).map((event) => [eventId(event), event]));
  const markerGroups = new Map();
  const markerKind = (reason, eventIds = []) => {
    const value = String(reason || "").toLowerCase();
    return newsEnabled && (value.includes("news") || eventIds.length) ? "news-rebalance" : value.includes("volume") || value.includes("spike") ? "volume-spike" : "scheduled-rebalance";
  };
  const addMarker = ({ date, reason, eventIds = [], order, plan }, index) => {
    const timestamp = new Date(date).getTime();
    if (!Number.isFinite(timestamp) || !rows.length || timestamp < new Date(rows[0].date).getTime() || timestamp > new Date(rows.at(-1).date).getTime()) return;
    const rowIndex = rows.reduce((best, row, current) => Math.abs(new Date(row.date).getTime() - timestamp) < Math.abs(new Date(rows[best].date).getTime() - timestamp) ? current : best, 0);
    const kind = markerKind(reason, eventIds);
    const key = `${rowIndex}|${kind}`;
    const marker = markerGroups.get(key) || { id: key || index, rowIndex, kind, reasons: new Set(), orders: [], plans: [], eventIds: new Set(), events: [] };
    if (reason) marker.reasons.add(reason);
    if (order) marker.orders.push(order);
    if (plan) marker.plans.push(plan);
    eventIds.forEach((id) => { marker.eventIds.add(id); const event = linkedById.get(id); if (event && !marker.events.some((item) => eventId(item) === id)) marker.events.push(event); });
    markerGroups.set(key, marker);
  };
  (orders || []).forEach((order, index) => {
    const ids = [...new Set([...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])])];
    addMarker({ date: order.executed_at || order.created_at, reason: order.reason, eventIds: ids, order }, index);
  });
  (rebalances || []).filter((plan) => plan.status !== "cancelled").forEach((plan, index) => {
    const ids = [...new Set([...(plan.event_ids || []), ...Object.values(plan.ticker_event_ids || {}).flat()])];
    addMarker({ date: plan.executed_at || plan.scheduled_for || plan.decision_at || plan.created_at, reason: plan.reason, eventIds: ids, plan }, `plan-${index}`);
  });
  const markers = symbol ? [] : [...markerGroups.values()].map((marker) => {
    const date = rows[marker.rowIndex]?.date;
    const reason = [...marker.reasons].join(", ");
    let linkedOrders = marker.orders;
    if (!linkedOrders.length && date) {
      const when = new Date(date).getTime();
      const nearby = (orders || []).filter((order) => Math.abs(new Date(order.executed_at || order.created_at).getTime() - when) <= 36 * 60 * 60 * 1000);
      const matching = nearby.filter((order) => markerKind(order.reason, [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])]) === marker.kind);
      linkedOrders = matching.length ? matching : nearby;
    }
    return { ...marker, orders: linkedOrders, timestamp: date, seriesName: series[0]?.name, kind: "rebalance", triggerKind: marker.kind, reason,
      events: marker.events, label: `${reason || "Portfolio rebalance"} · ${linkedOrders.length} trade${linkedOrders.length === 1 ? "" : "s"}`, offset: marker.kind === "news-rebalance" ? -5 : 5 };
  });
  const changeTickerSelection = (ticker) => setSelectedTickers((current) => {
    const selected = current === "top8" ? defaultTickers : current ?? availableTickers;
    return selected.includes(ticker) ? selected.filter((item) => item !== ticker) : [...selected, ticker];
  });
  const selectAll = () => setSelectedTickers(null);
  const deselectAll = () => setSelectedTickers([]);
  const selectedPortfolio = portfolios.find((portfolio) => portfolio.id === activePortfolioId);
  const targetCount = Number(selectedPortfolio?.config?.portfolio_size) || 20;
  const approximateTarget = number(100 / targetCount, 1);

  if (!allRows.length) return <div className="weight-chart-empty"><b>Weight history is not available yet</b><span>Daily portfolio snapshots will appear here as they are recorded.</span></div>;
  if (!rows.length) return <div className="weight-chart-empty"><b>No weight snapshots in this period</b><span>Try a longer time range to see earlier portfolio weights.</span></div>;

  return <div className="weight-chart-wrap">
    {!symbol && <div className="weight-chart-controls">
      {portfolios.length > 1 && <div className="segmented weight-portfolio-tabs" role="tablist" aria-label="Portfolio weights">{portfolios.map((portfolio) => <button key={portfolio.id} type="button" role="tab" aria-selected={portfolio.id === activePortfolioId} className={portfolio.id === activePortfolioId ? "active" : ""} onClick={() => onPortfolioChange?.(portfolio.id)}>{portfolio.news_enabled ? "News-aware" : "Normal strategy"}</button>)}</div>}
      <div className="weight-chart-tools">
        <div className="segmented compact weight-range-tabs" role="tablist" aria-label="Weight chart date range">{ranges.map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={range === value} className={range === value ? "active" : ""} onClick={() => setRange(value)}>{label}</button>)}</div>
        <details className="weight-stock-filter"><summary><span>Stocks</span><b>{selectedTickers === null ? "All" : `${visibleTickers.length} selected`}</b><i aria-hidden="true">⌄</i></summary>
          <div className="weight-stock-menu"><div className="weight-stock-menu-head"><b>Choose holdings</b><div className="weight-stock-menu-actions"><button type="button" onClick={selectAll} disabled={visibleTickers.length === availableTickers.length}>Select all</button><button type="button" onClick={deselectAll} disabled={visibleTickers.length === 0}>Deselect all</button></div></div><label className="weight-stock-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search company or ticker" aria-label="Search stocks"/></label><div className="weight-stock-options">{filteredOptions.map((ticker) => { const shares = sharesByTicker.get(ticker) || 0; return <label className="weight-stock-option" key={ticker}><input type="checkbox" checked={visibleTickers.includes(ticker)} onChange={() => changeTickerSelection(ticker)}/><TickerMark symbol={ticker} tickers={tickers}/><span className="weight-stock-option-name"><b>{companyByTicker.get(ticker) || ticker}</b><small>{ticker}</small></span><span className="weight-stock-option-shares">{number(shares, 0)} <small>shares</small></span></label>; })}{!filteredOptions.length && <p className="weight-stock-no-results">No matching companies</p>}</div><div className="weight-stock-menu-foot">{visibleTickers.length} of {availableTickers.length} stocks shown</div></div>
        </details>
      </div>
    </div>}
    {!visibleTickers.length && <div className="weight-selection-empty">No stocks selected. Choose one or more companies from the stock filter.</div>}
    {!!visibleTickers.length && <StackedWeightPlot series={stackSeries} rows={rows} markers={markers} height={height} focusSymbol={symbol} onMarker={onMarker || ((marker) => marker.events?.[0] && onEvent?.(marker.events[0]))} companyByTicker={companyByTicker} tickers={tickers} otherCount={otherTickers.length}/>}
    {!!visibleTickers.length && <div className="weight-chart-legend">{stackSeries.map((line) => <span key={line.name}><i style={{ background: line.color }}/><b>{line.name}</b></span>)}</div>}
    {!!visibleTickers.length && !symbol && <p className="weight-chart-note">{!newsEnabled ? `The normal strategy targets about ${approximateTarget}% per stock across ${targetCount} holdings, so similar bands are expected; market moves cause small daily differences.` : `The news-aware strategy starts near ${approximateTarget}% per stock, with qualifying news able to increase selected holdings.`} “Other holdings” combines stocks outside the filter. Hover an area for its exact weight; click a rebalance marker for details.</p>}
  </div>;
}

function StackedWeightPlot({ series, rows, markers, height, focusSymbol, onMarker, companyByTicker, tickers, otherCount }) {
  const [hover, setHover] = useState(null);
  const width = 920, pad = { left: 72, right: 22, top: 18, bottom: 44 };
  const plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
  const x = (index) => pad.left + index * plotWidth / Math.max(1, rows.length - 1);
  const totalByIndex = rows.map((_, index) => series.reduce((sum, item) => sum + (Number(item.data[index]?.value) || 0), 0));
  const maxTotal = Math.max(0, ...totalByIndex);
  const maxY = focusSymbol
    ? Math.max(1, Math.ceil(maxTotal * 1.2 * 2) / 2)
    : Math.ceil(Math.max(100, maxTotal) / 20) * 20;
  const y = (value) => pad.top + (maxY - value) * plotHeight / maxY;
  let running = rows.map(() => 0);
  const areas = series.map((item) => {
    const lower = running;
    const upper = rows.map((_, index) => lower[index] + (Number(item.data[index]?.value) || 0));
    const top = upper.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
    const bottom = lower.map((value, index) => ({ x: x(index), y: y(value) })).reverse().map((point) => `L${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const path = rows.length === 1
      ? `M${x(0) - 5},${y(upper[0])} L${x(0) + 5},${y(upper[0])} L${x(0) + 5},${y(lower[0])} L${x(0) - 5},${y(lower[0])} Z`
      : `${top} ${bottom} Z`;
    running = upper;
    return { ...item, lower, upper, path };
  });
  const tickIndexes = [...new Set([0, Math.floor((rows.length - 1) / 3), Math.floor((rows.length - 1) * 2 / 3), rows.length - 1])];
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => maxY * fraction);
  const hoveredArea = hover ? areas.find((area) => area.name === hover.name) : null;
  const hoveredRow = hover ? rows[hover.index] : null;
  const move = (event) => {
    const point = event.touches?.[0] || event.changedTouches?.[0] || event;
    const rect = event.currentTarget.getBoundingClientRect();
    const localX = (point.clientX - rect.left) * width / rect.width;
    const localY = (point.clientY - rect.top) * height / rect.height;
    if (localX < pad.left || localX > width - pad.right || localY < pad.top || localY > height - pad.bottom) { setHover(null); return; }
    const index = Math.max(0, Math.min(rows.length - 1, Math.round((localX - pad.left) / plotWidth * Math.max(1, rows.length - 1))));
    const valueAtCursor = (height - pad.bottom - localY) * maxY / plotHeight;
    const area = areas.find((item) => valueAtCursor >= item.lower[index] && valueAtCursor <= item.upper[index]);
    if (!area) { setHover(null); return; }
    setHover({ name: area.name, index, x: Math.max(8, Math.min(point.clientX + 14, window.innerWidth - 310)), y: Math.max(8, Math.min(point.clientY + 14, window.innerHeight - 145)) });
  };
  const hoveredWeight = hoveredArea && hoveredRow ? Number(hoveredArea.data[hover.index]?.value) || 0 : 0;
  const companyName = hoveredArea?.name === "Other holdings" ? `${otherCount} stocks` : companyByTicker.get(hoveredArea?.name) || hoveredArea?.name;
  return <div className="weight-stack-plot" onMouseLeave={() => setHover(null)}><svg className="performance-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Stacked area chart of portfolio weights over time" onMouseMove={move} onTouchStart={move} onTouchMove={move}>
    {yTicks.map((value) => <g key={value}><line x1={pad.left} x2={width - pad.right} y1={y(value)} y2={y(value)} className="chart-grid"/><text x={pad.left - 9} y={y(value) + 4} textAnchor="end" className="chart-axis">{number(value, focusSymbol ? 1 : 0)}%</text></g>)}
    {tickIndexes.map((index, tick) => <g key={index}><line x1={x(index)} x2={x(index)} y1={height - pad.bottom} y2={height - pad.bottom + 4} className="chart-tick"/><text x={x(index)} y={height - 10} textAnchor={tick === 0 ? "start" : tick === tickIndexes.length - 1 ? "end" : "middle"} className="chart-axis">{new Date(rows[index].date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</text></g>)}
    {areas.map((area) => <path key={area.name} d={area.path} fill={area.color} fillOpacity={hover?.name && hover.name !== area.name ? ".4" : ".76"} stroke={area.color} strokeWidth="1.1" className="weight-stack-area"><title>{area.name}</title></path>)}
    {hover && <line x1={x(hover.index)} x2={x(hover.index)} y1={pad.top} y2={height - pad.bottom} className="weight-stack-cursor"/>}
    {markers.map((marker, index) => { const markerIndex = marker.rowIndex; const markerX = x(markerIndex) + (index % 2 ? 4 : -4); return <g key={marker.id} className={`chart-marker rebalance ${marker.triggerKind || ""}`} role="button" tabIndex="0" aria-label={marker.label} onClick={() => onMarker?.(marker)} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onMarker?.(marker)}><line x1={markerX} x2={markerX} y1={pad.top} y2={height - pad.bottom} className="marker-line"/><circle cx={markerX} cy={pad.top + 8 + (index % 3) * 8} r="5"/><title>{marker.label}</title></g>; })}
  </svg>{hover && hoveredArea && hoveredRow && <div className="weight-area-tooltip" style={{ left: hover.x, top: hover.y }}><b>{hoveredArea.name !== "Other holdings" && <TickerMark symbol={hoveredArea.name} tickers={tickers}/>}<span>{hoveredArea.name}{hoveredArea.name === "Other holdings" ? ` · ${companyName}` : companyName !== hoveredArea.name ? ` · ${companyName}` : ""}</span></b><strong>{number(hoveredWeight, 2)}% of portfolio</strong><small>{new Date(hoveredRow.date).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</small>{hoveredArea.name === "Other holdings" && <small>Combined weight of stocks outside this selection</small>}</div>}</div>;
}
