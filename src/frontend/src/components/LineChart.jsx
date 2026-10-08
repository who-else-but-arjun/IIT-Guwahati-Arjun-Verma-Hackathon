import { useMemo, useState } from "react";
import { dateTime, formatReason, impactScore, money, number } from "../utils/format";

export function LineChart({ series = [], markers = [], mode = "value", dateRange = "all", height = 300, currency = "USD", onMarker, bottomPadding = 52 }) {
  const [hover, setHover] = useState(null);
  const [hoveredMarker, setHoveredMarker] = useState(null);
  const width = 920, pad = { l: 72, r: 22, t: 20, b: bottomPadding };
  const safeSeries = series.filter((line) => Array.isArray(line?.data));
  const rows = useMemo(() => safeSeries.flatMap((line) => line.data.map((point, index) => ({ ...point, index, line: line.name, color: line.color })).filter((point) => Number.isFinite(Number(point.value)))), [safeSeries]);
  if (!rows.length) return <div className="chart-empty">Performance history is not available yet.</div>;
  const values = rows.map((row) => Number(row.value));
  let min = Math.min(...values), max = Math.max(...values);
  if (max === min) { max += 1; min -= 1; }
  const xCount = Math.max(2, ...safeSeries.map((s) => s.data.length));
  const x = (index) => pad.l + index * (width - pad.l - pad.r) / (xCount - 1);
  const y = (value) => pad.t + (max - value) * (height - pad.t - pad.b) / (max - min);
  const paths = safeSeries.map((line) => line.data.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(Number(point.value)).toFixed(1)}`).join(" "));
  const selectedPoint = hover == null ? null : safeSeries.map((line) => ({ name: line.name, color: line.color, point: line.data[hover] })).filter((entry) => entry.point);
  const dateSeries = safeSeries.reduce((longest, line) => line.data.length > longest.length ? line.data : longest, []);
  const firstDate = new Date(dateSeries[0]?.timestamp || dateSeries[0]?.date);
  const lastDate = new Date(dateSeries.at(-1)?.timestamp || dateSeries.at(-1)?.date);
  const spanDays = (lastDate - firstDate) / 86400000;
  const dateOptions = dateRange === "1m" || dateRange === "3m"
    ? { month: "short", day: "numeric" }
    : (dateRange === "all" && spanDays > 550 ? { year: "numeric" } : { month: "short", year: "2-digit" });
  const tickCount = Math.min(5, dateSeries.length);
  const dateTicks = Array.from({ length: tickCount }, (_, i) => {
    const index = Math.round(i * (dateSeries.length - 1) / Math.max(1, tickCount - 1));
    const point = dateSeries[index];
    const date = new Date(point?.timestamp || point?.date);
    return { index, label: Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(undefined, dateOptions).format(date) };
  }).filter((tick, i, ticks) => tick.label && (!i || tick.label !== ticks[i - 1].label));
  const markerContent = hoveredMarker?.marker;
  const markerEvents = markerContent?.events || [];
  const markerOrders = markerContent?.orders || [];
  return <div className="chart-wrap" onMouseLeave={() => { setHover(null); setHoveredMarker(null); }}>
    <svg className="performance-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Portfolio performance chart">
      {[0, 1, 2, 3].map((i) => { const value = max - (max - min) * i / 3; return <g key={i}><line x1={pad.l} x2={width - pad.r} y1={y(value)} y2={y(value)} className="chart-grid"/><text x={pad.l - 10} y={y(value) + 4} textAnchor="end" className="chart-axis">{mode === "value" ? money(value, currency, true) : `${number(value, 1)}%`}</text></g>; })}
      {dateTicks.map((tick, i) => <g key={`${tick.index}-${i}`}><line x1={x(tick.index)} x2={x(tick.index)} y1={height - pad.b} y2={height - pad.b + 4} className="chart-tick"/><text x={x(tick.index)} y={height - 12} textAnchor={i === 0 ? "start" : i === dateTicks.length - 1 ? "end" : "middle"} className="chart-axis chart-date-axis">{tick.label}</text></g>)}
      {safeSeries.map((line, i) => <path key={line.name} d={paths[i]} className="chart-line" stroke={line.color} />)}
      {hover != null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={height - pad.b} className="chart-hover-line"/>}
      {dateSeries.map((point, index) => <rect key={index} x={x(index) - (width / xCount) / 2} y={pad.t} width={width / xCount} height={height - pad.t - pad.b} fill="transparent" onMouseEnter={() => setHover(index)} />)}
      {markers.map((marker, i) => {
        const markerSeries = safeSeries.find((line) => line.name === marker.seriesName && line.data.length) || safeSeries.find((line) => line.data.length);
        if (!markerSeries) return null;
        const markerIndex = marker.timestamp ? markerSeries.data.reduce((best, point, j) => Math.abs(new Date(point.timestamp || point.date).getTime() - new Date(marker.timestamp).getTime()) < Math.abs(new Date(markerSeries.data[best]?.timestamp || markerSeries.data[best]?.date).getTime() - new Date(marker.timestamp).getTime()) ? j : best, 0) : marker.index;
        const index = Math.max(0, Math.min(xCount - 1, markerIndex));
        const markerX = x(index) + (Number(marker.offset) || 0);
        const point = markerSeries.data[Math.max(0, Math.min(markerSeries.data.length - 1, markerIndex))];
        const cy = point ? y(Number(point.value)) : pad.t + 7;
        const markerClasses = ["chart-marker", marker.kind || "event", marker.triggerKind].filter(Boolean).join(" ");
        return <g key={`${marker.id || marker.label}-${i}`} className={markerClasses} tabIndex="0" role="button" aria-label={marker.label} onMouseEnter={() => { setHover(index); setHoveredMarker({ marker, index, cx: markerX, cy }); }} onFocus={() => { setHover(index); setHoveredMarker({ marker, index, cx: markerX, cy }); }} onBlur={() => setHoveredMarker(null)} onClick={() => onMarker?.(marker)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onMarker?.(marker)}><line x1={markerX} x2={markerX} y1={pad.t} y2={height - pad.b} className="marker-line"/><circle cx={markerX} cy={cy} r="7"/><title>{marker.label}</title></g>;
      })}
    </svg>
    {selectedPoint?.[0]?.point && !markerContent && <div className="chart-tooltip" style={{ left: `${Math.min(78, Math.max(7, (hover / (xCount - 1)) * 100))}%` }}><b>{dateTime(selectedPoint[0].point.timestamp || selectedPoint[0].point.date)}</b>{selectedPoint.map((item) => <div key={item.name}><i style={{ background: item.color }}/>{item.name}<strong>{mode === "value" ? money(item.point.value, currency) : `${number(item.point.value, 2)}%`}</strong></div>)}</div>}
    {markerContent && <div className="chart-marker-tooltip" style={{ left: `${Math.min(76, Math.max(5, hoveredMarker.cx / width * 100))}%`, top: `${Math.min(68, Math.max(3, hoveredMarker.cy / height * 100))}%` }}>
      <span className="chart-marker-tooltip-kicker">{markerContent.kind === "rebalance" ? "REBALANCE ACTIVITY" : "NEWS EVENT"}</span>
      <b>{markerContent.headline || markerContent.label || "Portfolio event"}</b>
      <small>{dateTime(markerContent.timestamp)}{markerContent.reason ? ` · ${formatReason(markerContent.reason)}` : ""}</small>
      {markerEvents.slice(0, 2).map((event, i) => <span className="chart-marker-tooltip-line" key={event.id || event.event_id || i}>{event.headline}</span>)}
      {markerContent.sentiment?.score != null && <span className="chart-marker-tooltip-line">Sentiment {number(markerContent.sentiment.score, 2)} · impact {markerContent.sentiment.impact_score == null ? "—" : impactScore(markerContent.sentiment.impact_score)}</span>}
      {markerOrders.length > 0 && <span className="chart-marker-tooltip-line">{markerOrders.length} trades · {markerOrders.reduce((sum, order) => sum + (Number(order.gross_value) || 0), 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} turnover</span>}
      {markerContent.kind === "event" && !markerEvents.length && markerContent.headline && <span className="chart-marker-tooltip-line">Sentiment {markerContent.sentiment?.score == null ? "—" : number(markerContent.sentiment.score, 2)} · {markerContent.category || "News"}</span>}
      <i>Click for full details</i>
    </div>}
  </div>;
}

export function PriceHistoryChart({ bars = [], markers = [], currency = "USD", height = 250, onViewChange }) {
  const [view, setView] = useState("line");
  const validBars = (bars || []).filter((bar) => Number.isFinite(new Date(bar.timestamp || bar.date).getTime()) && Number.isFinite(Number(bar.close)));
  const lineSeries = [{ name: "Close", color: "var(--ink)", data: validBars.map((bar) => ({ timestamp: bar.timestamp || bar.date, value: Number(bar.close) })) }];
  const candleWidth = 920, pad = { l: 72, r: 22, t: 18, b: 42 };
  const highs = validBars.map((bar) => Number(bar.high ?? bar.close)).filter(Number.isFinite);
  const lows = validBars.map((bar) => Number(bar.low ?? bar.close)).filter(Number.isFinite);
  let min = Math.min(...lows), max = Math.max(...highs);
  if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
  if (min === max) { min -= 1; max += 1; }
  const y = (value) => pad.t + (max - value) * (height - pad.t - pad.b) / (max - min);
  const x = (index) => pad.l + index * (candleWidth - pad.l - pad.r) / Math.max(1, validBars.length - 1);
  const ticks = Array.from({ length: 4 }, (_, i) => max - (max - min) * i / 3);
  const dateTicks = Array.from({ length: Math.min(4, validBars.length) }, (_, i) => {
    const index = Math.round(i * (validBars.length - 1) / Math.max(1, Math.min(4, validBars.length) - 1));
    return { index, label: new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(validBars[index].timestamp || validBars[index].date)) };
  }).filter((tick, i, all) => !i || tick.label !== all[i - 1].label);
  const maxVolume = Math.max(1, ...validBars.map((bar) => Number(bar.volume) || 0));
  const markerIndexes = validBars.length ? (markers || []).map((marker) => {
    const time = new Date(marker.timestamp || marker.date).getTime();
    const index = Number.isFinite(time) ? validBars.reduce((best, bar, current) => Math.abs(new Date(bar.timestamp || bar.date).getTime() - time) < Math.abs(new Date(validBars[best].timestamp || validBars[best].date).getTime() - time) ? current : best, 0) : Number(marker.index);
    return { ...marker, index: Math.max(0, Math.min(validBars.length - 1, index)) };
  }).filter((marker) => Number.isFinite(marker.index)) : [];
  return <section className={`price-history-chart ${view === "line" ? "line-view" : "ohlc-view"}`} aria-label="Stock price history chart">
    <div className="price-chart-switch" role="tablist" aria-label="Price chart type"><button role="tab" aria-selected={view === "line"} className={view === "line" ? "active" : ""} onClick={() => { setView("line"); onViewChange?.("line"); }}>Line</button><button role="tab" aria-selected={view === "ohlc"} className={view === "ohlc" ? "active" : ""} onClick={() => { setView("ohlc"); onViewChange?.("ohlc"); }}>OHLC</button></div>
    {view === "line" ? <LineChart series={lineSeries} markers={markers} mode="value" currency={currency} height={height} bottomPadding={pad.b}/> : validBars.length < 2 ? <div className="chart-empty">OHLC history needs at least two valid price bars.</div> : <svg className="performance-chart ohlc-chart" viewBox={`0 0 ${candleWidth} ${height}`} role="img" aria-label="OHLC candlestick chart with volume">
      {ticks.map((value, index) => <g key={index}><line x1={pad.l} x2={candleWidth - pad.r} y1={y(value)} y2={y(value)} className="chart-grid"/><text x={pad.l - 9} y={y(value) + 4} textAnchor="end" className="chart-axis">{money(value, currency, true)}</text></g>)}
      {validBars.map((bar, index) => {
        const open = Number(bar.open ?? bar.close), close = Number(bar.close), high = Number(bar.high ?? Math.max(open, close)), low = Number(bar.low ?? Math.min(open, close));
        const positive = close >= open, candleX = x(index), bodyTop = Math.min(y(open), y(close)), bodyHeight = Math.max(1.5, Math.abs(y(open) - y(close))), volumeHeight = (Number(bar.volume) || 0) / maxVolume * 24;
        return <g key={`${bar.timestamp || bar.date}-${index}`}><line x1={candleX} x2={candleX} y1={y(high)} y2={y(low)} className={positive ? "ohlc-wick up" : "ohlc-wick down"}/><rect x={candleX - 3.5} y={bodyTop} width="7" height={bodyHeight} className={positive ? "ohlc-body up" : "ohlc-body down"}><title>{`${new Date(bar.timestamp || bar.date).toLocaleString()} · O ${money(open, currency)} · H ${money(high, currency)} · L ${money(low, currency)} · C ${money(close, currency)} · Vol ${number(bar.volume, 0)}`}</title></rect><rect x={candleX - 3} y={height - pad.b - volumeHeight} width="6" height={volumeHeight} className={positive ? "ohlc-volume up" : "ohlc-volume down"}/></g>;
      })}
      {markerIndexes.map((marker, index) => { const bar = validBars[marker.index]; return <g className="ohlc-news-marker" key={marker.id || index}><circle cx={x(marker.index)} cy={y(Number(bar.close))} r="4"><title>{marker.label || "News event"}</title></circle></g>; })}
      {dateTicks.map((tick, index) => <text key={index} x={x(tick.index)} y={height - 11} textAnchor={index === 0 ? "start" : index === dateTicks.length - 1 ? "end" : "middle"} className="chart-axis chart-date-axis">{tick.label}</text>)}
    </svg>}
    {view === "ohlc" && validBars.length >= 2 && <div className="ohlc-legend"><span><i className="ohlc-up-swatch"/>Close above open</span><span><i className="ohlc-down-swatch"/>Close below open</span><span><i className="ohlc-volume-swatch"/>Volume</span>{markers.length > 0 && <span><i className="ohlc-news-swatch"/>News publication</span>}</div>}
  </section>;
}
