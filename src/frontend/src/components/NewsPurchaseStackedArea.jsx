import { useEffect, useMemo, useState } from "react";
import { api, eventId, eventTime } from "../services/api";
import { dateTime, number } from "../utils/format";
import { TickerMark } from "./AppShell";

const colors = ["#df3038", "#167b60", "#3768a5", "#b77b20", "#7b55a3", "#238997", "#b34f7d", "#6d747e", "#a0a3a9"];
export function NewsPurchaseStackedArea({ orders = [], events = [], tickers = [], onEvent }) {
  const [hover, setHover] = useState(null);
  const [fetchedEvents, setFetchedEvents] = useState({});
  const [loadingEventIds, setLoadingEventIds] = useState(() => new Set());
  const eventById = useMemo(() => new Map((events || []).map((event) => [eventId(event), event])), [events]);

  const history = useMemo(() => {
    const byDateTicker = new Map();
    const totalsByTicker = new Map();
    for (const order of orders || []) {
      if (String(order.side).toLowerCase() !== "buy" || !(Number(order.quantity) > 0)) continue;
      const ids = [...new Set([...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])])];
      if (!ids.length) continue;
      const ticker = String(order.ticker_id || "").toUpperCase();
      const stamp = new Date(order.executed_at || order.created_at);
      if (!ticker || !Number.isFinite(stamp.getTime())) continue;
      const date = stamp.toISOString().slice(0, 10);
      if (!byDateTicker.has(date)) byDateTicker.set(date, new Map());
      const day = byDateTicker.get(date);
      if (!day.has(ticker)) day.set(ticker, []);
      day.get(ticker).push(order);
      totalsByTicker.set(ticker, (totalsByTicker.get(ticker) || 0) + Number(order.quantity));
    }
    const dates = [...byDateTicker.keys()].sort();
    const ranked = [...totalsByTicker].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const topTickers = ranked.slice(0, 8).map(([ticker]) => ticker);
    const otherTickers = ranked.slice(8).map(([ticker]) => ticker);
    const definitions = [...topTickers.map((ticker) => ({ key: ticker, tickers: [ticker] }))];
    if (otherTickers.length) definitions.push({ key: "Other", tickers: otherTickers });
    const running = new Map(definitions.map((item) => [item.key, 0]));
    const points = dates.map((date) => {
      const day = byDateTicker.get(date);
      for (const item of definitions) {
        const buys = item.tickers.flatMap((ticker) => day.get(ticker) || []);
        running.set(item.key, running.get(item.key) + buys.reduce((sum, order) => sum + Number(order.quantity), 0));
      }
      return { date, values: Object.fromEntries(running), buys: day };
    });
    return { points, definitions, otherTickers, totalShares: ranked.reduce((sum, [, quantity]) => sum + quantity, 0) };
  }, [orders]);

  const openLinkedEvent = async (id) => {
    const existing = eventById.get(id) || fetchedEvents[id];
    if (existing) { onEvent?.(existing); return; }
    setLoadingEventIds((current) => new Set(current).add(id));
    try {
      const response = await api.event(id);
      const event = response?.event || response;
      setFetchedEvents((current) => ({ ...current, [id]: event }));
      onEvent?.(event);
    } catch { /* Keep the link available so the user can retry. */ }
    finally { setLoadingEventIds((current) => { const next = new Set(current); next.delete(id); return next; }); }
  };

  const width = 920, height = 280, pad = { left: 54, right: 18, top: 14, bottom: 38 };
  const plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
  const maxTotal = Math.max(1, ...history.points.map((point) => Object.values(point.values).reduce((sum, value) => sum + value, 0)));
  const x = (index) => pad.left + index * plotWidth / Math.max(1, history.points.length - 1);
  const y = (value) => pad.top + (maxTotal - value) * plotHeight / maxTotal;
  let running = history.points.map(() => 0);
  const areas = history.definitions.map((definition, seriesIndex) => {
    const lower = running;
    const upper = history.points.map((point, index) => lower[index] + (Number(point.values[definition.key]) || 0));
    const topPath = upper.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
    const path = history.points.length === 1
      ? `M${x(0) - 5},${y(upper[0])} L${x(0) + 5},${y(upper[0])} L${x(0) + 5},${y(lower[0])} L${x(0) - 5},${y(lower[0])} Z`
      : `${topPath} ${lower.map((value, index) => ({ x: x(index), y: y(value) })).reverse().map((point) => `L${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")} Z`;
    running = upper;
    return { ...definition, color: colors[seriesIndex % colors.length], lower, upper, path };
  });
  const dateTicks = Array.from(new Set([0, Math.floor((history.points.length - 1) / 3), Math.floor((history.points.length - 1) * 2 / 3), history.points.length - 1]));
  const hoveredArea = hover ? areas.find((area) => area.key === hover.key) : null;
  const hoveredPoint = hover ? history.points[hover.index] : null;
  const recentBuys = hoveredArea && hoveredPoint ? (() => {
    const direct = hoveredArea.tickers.flatMap((ticker) => hoveredPoint.buys.get(ticker) || []);
    if (direct.length) return { orders: direct, date: hoveredPoint.date, direct: true };
    for (let index = hover.index - 1; index >= 0; index -= 1) {
      const prior = hoveredArea.tickers.flatMap((ticker) => history.points[index].buys.get(ticker) || []);
      if (prior.length) return { orders: prior, date: history.points[index].date, direct: false };
    }
    return { orders: [], date: hoveredPoint.date, direct: false };
  })() : null;
  const linkedIds = [...new Set((recentBuys?.orders || []).flatMap((order) => [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])]))];
  const displayTicker = hoveredArea?.key || "";
  const displayName = displayTicker === "Other" ? `Other · ${hoveredArea?.tickers.length || 0} stocks` : displayTicker;
  const batchShares = (recentBuys?.orders || []).reduce((sum, order) => sum + (Number(order.quantity) || 0), 0);

  useEffect(() => {
    if (!hoveredArea || !recentBuys?.orders?.length) return;
    const ids = [...new Set(recentBuys.orders.flatMap((order) => [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])]))].slice(0, 3);
    const missing = ids.filter((id) => !eventById.has(id) && !fetchedEvents[id] && !loadingEventIds.has(id));
    if (!missing.length) return;
    setLoadingEventIds((current) => new Set([...current, ...missing]));
    Promise.allSettled(missing.map(async (id) => {
      const response = await api.event(id);
      return [id, response?.event || response];
    })).then((results) => {
      const resolved = results.filter((result) => result.status === "fulfilled");
      if (resolved.length) setFetchedEvents((current) => ({ ...current, ...Object.fromEntries(resolved.map((result) => result.value)) }));
      setLoadingEventIds((current) => { const next = new Set(current); missing.forEach((id) => next.delete(id)); return next; });
    });
  }, [hover?.key, hover?.index, eventById, fetchedEvents, loadingEventIds, history]);

  if (!history.points.length) return <div className="weight-chart-empty"><b>No news-linked purchases in this portfolio yet</b><span>Completed buy orders tied to news events will appear here.</span></div>;

  const handleMove = (event) => {
    const point = event.touches?.[0] || event.changedTouches?.[0] || event;
    const rect = event.currentTarget.getBoundingClientRect();
    const localX = (point.clientX - rect.left) * width / rect.width;
    const localY = (point.clientY - rect.top) * height / rect.height;
    if (localX < pad.left || localX > width - pad.right || localY < pad.top || localY > height - pad.bottom) { setHover(null); return; }
    const index = Math.max(0, Math.min(history.points.length - 1, Math.round((localX - pad.left) / plotWidth * Math.max(1, history.points.length - 1))));
    const valueAtCursor = maxTotal - (localY - pad.top) * maxTotal / plotHeight;
    const area = areas.find((item) => valueAtCursor >= item.lower[index] && valueAtCursor <= item.upper[index]);
    if (!area) { setHover(null); return; }
    const left = Math.max(8, Math.min(point.clientX + 14, window.innerWidth - 330));
    const top = Math.max(8, Math.min(point.clientY + 14, window.innerHeight - 355));
    setHover({ key: area.key, index, left, top });
  };

  return <div className="news-purchase-area-wrap" onMouseLeave={() => setHover(null)}>
    <div className="news-purchase-area-summary"><b>{number(history.totalShares, 0)}</b><span>news-linked shares purchased</span><small>{history.definitions.length > 8 ? "Top 8 stocks plus the remaining holdings" : "All stocks shown"}</small></div>
    <svg className="news-purchase-area" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Cumulative news-linked shares purchased by stock over time" onMouseMove={handleMove} onTouchStart={handleMove} onTouchMove={handleMove}>
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => { const value = maxTotal * fraction; return <g key={fraction}><line x1={pad.left} x2={width - pad.right} y1={y(value)} y2={y(value)} className="chart-grid"/><text x={pad.left - 8} y={y(value) + 3} textAnchor="end" className="chart-axis">{number(value, 0)}</text></g>; })}
      {dateTicks.map((index) => <g key={index}><line x1={x(index)} x2={x(index)} y1={height - pad.bottom} y2={height - pad.bottom + 4} className="chart-tick"/><text x={x(index)} y={height - 9} textAnchor={index === 0 ? "start" : index === history.points.length - 1 ? "end" : "middle"} className="chart-axis">{new Date(`${history.points[index].date}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: history.points.length > 1 && history.points.at(-1).date.slice(0, 4) !== history.points[0].date.slice(0, 4) ? "2-digit" : undefined })}</text></g>)}
      {areas.map((area) => <path key={area.key} d={area.path} fill={area.color} fillOpacity=".76" stroke={area.color} strokeWidth="1.2" className={`news-purchase-area-layer${hover?.key === area.key ? " active" : ""}`}><title>{area.key}</title></path>)}
      {hoveredPoint && <line x1={x(hover.index)} x2={x(hover.index)} y1={pad.top} y2={height - pad.bottom} className="news-purchase-area-cursor"/>}
    </svg>
    <div className="weight-chart-legend news-purchase-area-legend">{areas.map((area) => <span key={area.key}><i style={{ background: area.color }}/><b>{area.key}</b></span>)}</div>
    {hover && hoveredArea && recentBuys && <div className="purchase-area-tooltip" style={{ left: hover.left, top: hover.top }}>
      <b>{displayTicker !== "Other" && <TickerMark symbol={displayTicker} tickers={tickers}/>}<span>{displayName} · {recentBuys.orders.length} news-linked buy{recentBuys.orders.length === 1 ? "" : "s"}</span></b>
      <span>{number(batchShares, 0)} shares purchased{recentBuys.direct ? " on this date" : ` · latest buy ${dateTime(recentBuys.date)}`}</span>
      <small className="purchase-area-tooltip-date">{dateTime(hoveredPoint.date)} · cumulative {number(hoveredPoint.values[hoveredArea.key], 0)} shares</small>
      {displayTicker === "Other" && hoveredArea.tickers.map((ticker) => { const count = (recentBuys.orders || []).filter((order) => order.ticker_id?.toUpperCase() === ticker).length; return count ? <small className="purchase-area-other-ticker" key={ticker}>{ticker} · {count} buy{count === 1 ? "" : "s"}</small> : null; })}
      {linkedIds.slice(0, 3).map((id) => { const linkedEvent = eventById.get(id) || fetchedEvents[id]; return <button type="button" key={id} onClick={() => openLinkedEvent(id)}><small>{linkedEvent ? `Linked news event · ${dateTime(eventTime(linkedEvent))}` : loadingEventIds.has(id) ? "Loading linked event…" : "Linked news event"}</small><b>{linkedEvent?.headline || "Open news event"}</b></button>; })}
      {!linkedIds.length && <span>No linked story is available for this purchase.</span>}
    </div>}
    <p className="weight-chart-note">Stacked areas show cumulative shares bought in news-linked orders. Hover a stock to see the nearest purchase batch and open its story.</p>
  </div>;
}
