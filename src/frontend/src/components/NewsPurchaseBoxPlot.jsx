import { useMemo, useState } from "react";
import { api, eventId, eventTime } from "../services/api";
import { dateTime, number } from "../utils/format";
import { TickerMark } from "./AppShell";

const quantile = (values, fraction) => {
  if (!values.length) return 0;
  const position = (values.length - 1) * fraction;
  const lower = Math.floor(position), upper = Math.ceil(position);
  return values[lower] + (values[upper] - values[lower]) * (position - lower);
};

export function NewsPurchaseBoxPlot({ orders = [], events = [], tickers = [], onEvent }) {
  const [hoveredTicker, setHoveredTicker] = useState("");
  const [fetchedEvents, setFetchedEvents] = useState({});
  const [loadingEventIds, setLoadingEventIds] = useState(() => new Set());
  const eventById = useMemo(() => new Map((events || []).map((event) => [eventId(event), event])), [events]);
  const rows = useMemo(() => {
    const grouped = new Map();
    for (const order of orders || []) {
      if (String(order.side).toLowerCase() !== "buy" || !(Number(order.quantity) > 0)) continue;
      const ids = [...new Set([...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])])];
      if (!ids.length) continue;
      const ticker = String(order.ticker_id || "").toUpperCase();
      if (!ticker) continue;
      const row = grouped.get(ticker) || { ticker, trades: [], events: new Map(), eventIds: new Set() };
      row.trades.push(order);
      for (const id of ids) { row.eventIds.add(id); if (eventById.has(id)) row.events.set(id, eventById.get(id)); }
      grouped.set(ticker, row);
    }
    return [...grouped.values()].map((row) => {
      const values = row.trades.map((trade) => Number(trade.quantity)).sort((a, b) => a - b);
      return { ...row, min: values[0], q1: quantile(values, 0.25), median: quantile(values, 0.5), q3: quantile(values, 0.75), max: values.at(-1) };
    }).sort((a, b) => b.median - a.median).slice(0, 12);
  }, [orders, eventById]);
  if (!rows.length) return <div className="weight-chart-empty"><b>No news-linked purchases in this portfolio yet</b><span>Completed buy orders tied to news events will appear here.</span></div>;

  const width = 920, left = 156, right = 24, rowHeight = 42, top = 18;
  const height = top + rows.length * rowHeight + 28;
  const max = Math.max(1, ...rows.map((row) => row.max));
  const x = (value) => left + value / max * (width - left - right);
  const active = rows.find((row) => row.ticker === hoveredTicker);
  const openLinkedEvent = async (id) => {
    const existing = eventById.get(id) || fetchedEvents[id];
    if (existing) { onEvent?.(existing); return; }
    setLoadingEventIds((current) => new Set(current).add(id));
    try {
      const event = await api.event(id);
      setFetchedEvents((current) => ({ ...current, [id]: event }));
      onEvent?.(event);
    } catch { /* Keep the linked item visible so the user can retry. */ }
    finally { setLoadingEventIds((current) => { const next = new Set(current); next.delete(id); return next; }); }
  };
  return <div className="news-purchase-boxplot-wrap" onMouseLeave={() => setHoveredTicker("")}>
    <svg className="news-purchase-boxplot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Distribution of shares bought in news-linked trades by stock">
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => { const value = max * fraction; return <g key={fraction}><line x1={x(value)} x2={x(value)} y1={top - 8} y2={height - 22} className="chart-grid"/><text x={x(value)} y={height - 6} textAnchor="middle" className="chart-axis">{number(value, 0)} shares</text></g>; })}
      {rows.map((row, index) => { const y = top + index * rowHeight + rowHeight / 2; return <g className={`purchase-box-row${hoveredTicker === row.ticker ? " active" : ""}`} key={row.ticker} onMouseEnter={() => setHoveredTicker(row.ticker)}>
        <text x={left - 12} y={y + 3} textAnchor="end" className="chart-axis">{row.ticker}</text>
        <line x1={x(row.min)} x2={x(row.max)} y1={y} y2={y} className="purchase-box-whisker"/>
        <line x1={x(row.min)} x2={x(row.min)} y1={y - 6} y2={y + 6} className="purchase-box-whisker"/>
        <line x1={x(row.max)} x2={x(row.max)} y1={y - 6} y2={y + 6} className="purchase-box-whisker"/>
        <rect x={x(row.q1)} y={y - 9} width={Math.max(2, x(row.q3) - x(row.q1))} height="18" rx="2" className="purchase-box-range"/>
        <line x1={x(row.median)} x2={x(row.median)} y1={y - 10} y2={y + 10} className="purchase-box-median"/>
        <title>{`${row.ticker} · ${row.trades.length} buys · median ${number(row.median, 0)} shares · ${[...row.events.values()].map((event) => event.headline).join(" | ")}`}</title>
      </g>; })}
    </svg>
    {active && <div className="purchase-box-tooltip"><b><TickerMark symbol={active.ticker} tickers={tickers}/>{active.ticker} · {active.trades.length} news-linked buys</b><span>Shares purchased: median {number(active.median, 0)} · range {number(active.min, 0)}–{number(active.max, 0)}</span>{[...active.eventIds].slice(0, 3).map((id) => { const event = eventById.get(id) || fetchedEvents[id]; return <button type="button" key={id} onClick={() => openLinkedEvent(id)}><small>{event ? dateTime(eventTime(event)) : loadingEventIds.has(id) ? "Loading linked event…" : "Linked news event"}</small>{event?.headline || "Open news event"}</button>; })}</div>}
    <p className="weight-chart-note">Boxes show the middle half of share quantities bought in news-linked trades; whiskers span the smallest to largest purchase. Hover a stock, then open a linked story.</p>
  </div>;
}
