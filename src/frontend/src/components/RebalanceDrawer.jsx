import { useEffect, useMemo, useState } from "react";
import { Drawer, NewsCategoryIcon, TickerMark } from "./AppShell";
import { api, eventId, eventTime } from "../services/api";
import { cleanText, dateTime, formatReason, impactScore, money, number, percent } from "../utils/format";

export function RebalanceDetailDrawer({ row, portfolios = [], events = [], tickers = [], onClose, onEvent, onTicker }) {
  const portfolio = portfolios.find((item) => item.id === row.portfolio_id);
  const currency = portfolio?.currency || "USD";
  const orders = row.orders || [];
  const plan = row.plan;
  const eventIds = row.eventIds || [];
  const [fetchedEvents, setFetchedEvents] = useState([]);
  const eventKey = eventIds.join(",");
  useEffect(() => {
    let cancelled = false;
    const availableIds = new Set([...(events || []), ...(row.events || [])].map(eventId));
    const missing = eventIds.filter((id) => id && !availableIds.has(id)).slice(-20);
    if (!missing.length) { setFetchedEvents([]); return undefined; }
    Promise.allSettled(missing.map((id) => api.event(id))).then((results) => {
      if (!cancelled) setFetchedEvents(results.filter((item) => item.status === "fulfilled").map((item) => item.value.event || item.value));
    });
    return () => { cancelled = true; };
  }, [eventKey, events, row.events]);
  const linkedEvents = useMemo(() => {
    const byId = new Map();
    for (const event of [...(events || []), ...(row.events || []), ...fetchedEvents]) {
      const id = eventId(event);
      if (id && eventIds.includes(id)) byId.set(id, event);
    }
    return [...byId.values()];
  }, [events, row.events, fetchedEvents, eventKey]);
  const targets = Object.entries(plan?.target_weights || {}).filter(([, weight]) => Number(weight) > 0).sort((a, b) => Number(b[1]) - Number(a[1]));
  const tickerEventMap = plan?.ticker_event_ids || {};
  const currentByTicker = new Map((portfolio?.positions || []).map((position) => [position.ticker_id, Number(position.market_value) || Number(position.shares) * Number(position.last_price) || 0]));
  const portfolioValue = Number(portfolio?.portfolio_value) || Number(portfolio?.cash || 0) + [...currentByTicker.values()].reduce((sum, value) => sum + value, 0);
  const estimates = new Map(targets.map(([ticker, weight]) => [ticker, { value: Number(weight) * portfolioValue, delta: Number(weight) * portfolioValue - (currentByTicker.get(ticker) || 0) }]));
  for (const [ticker, currentValue] of currentByTicker) if (!estimates.has(ticker)) estimates.set(ticker, { value: 0, delta: -currentValue });
  const estimatedBuy = [...estimates.values()].reduce((sum, item) => sum + Math.max(0, item.delta), 0);
  const estimatedSell = [...estimates.values()].reduce((sum, item) => sum + Math.max(0, -item.delta), 0);
  const buyValue = row.pending ? estimatedBuy : orders.filter((order) => order.side === "buy").reduce((sum, order) => sum + (Number(order.gross_value) || 0), 0);
  const sellValue = row.pending ? estimatedSell : orders.filter((order) => order.side === "sell").reduce((sum, order) => sum + (Number(order.gross_value) || 0), 0);
  const feeValue = row.pending ? (buyValue + sellValue) * (Number(portfolio?.config?.transaction_cost) || 0)
    : orders.length ? row.fees ?? orders.reduce((sum, order) => sum + (Number(order.transaction_cost) || 0), 0) : null;
  const executedValue = (value) => value == null ? "—" : money(value, currency);
  return <Drawer title={row.pending ? "Scheduled rebalance" : "Rebalance details"} eyebrow={row.pending ? "PENDING STRATEGY DECISION" : "PORTFOLIO REBALANCING"} onClose={onClose}>
    <div className="marker-detail-content rebalance-detail-content">
      <p className="detail-meta">{portfolio?.name || "Paper portfolio"} · {portfolio?.news_enabled ? "News + Normal Rebalancing" : "Normal Rebalancing"}</p>
      <h3 className="rebalance-trigger">{formatReason(row.reason)}</h3>
      <p className="detail-meta">Decision {dateTime(row.decision_at || row.created_at)}{row.pending ? " · Scheduled " + dateTime(row.scheduled_for) : row.executed_at ? " · Executed " + dateTime(row.executed_at) : ""}</p>
      <div className="rebalance-summary-grid">
        <div><small>{row.pending ? "TARGET POSITIONS" : "TRADES"}</small><b>{row.pending ? targets.length : orders.length || "—"}</b></div>
        <div><small>{row.pending ? "EST. BUY VALUE" : "BUY VALUE"}</small><b>{row.pending ? money(buyValue, currency) : executedValue(orders.length ? buyValue : null)}</b></div>
        <div><small>{row.pending ? "EST. SELL VALUE" : "SELL VALUE"}</small><b>{row.pending ? money(sellValue, currency) : executedValue(orders.length ? sellValue : null)}</b></div>
        <div><small>{row.pending ? "EST. FEES" : "FEES"}</small><b>{row.pending ? money(feeValue, currency) : executedValue(feeValue)}</b></div>
      </div>
      {row.pending && <section className="drawer-section"><h4>Execution status</h4><div className="rebalance-status-box"><span className="status-pill pending">Pending</span><span>Targets are scheduled for {dateTime(row.scheduled_for)}. No order is treated as executed until the trade records arrive.</span></div>{plan?.last_error && <p className="drawer-error">{plan.last_error}</p>}</section>}
      {!row.pending && <section className="drawer-section"><h4>Executed trades · {orders.length}</h4>{orders.length ? <TradeTable orders={orders} currency={currency} onTicker={onTicker} events={linkedEvents} onEvent={onEvent}/> : <p className="muted">{plan?.status === "filled" ? "This rebalance plan was marked complete, but no linked trade records were returned." : "No execution records are available for this rebalance."}</p>}</section>}
      {!row.pending && targets.length > 0 && <section className="drawer-section"><h4>Target weights at decision · {targets.length}</h4><p className="muted">These are the saved portfolio targets for this rebalance. Executed quantities are listed above when order records are available.</p><div className="rebalance-target-chips">{targets.map(([ticker, weight]) => {
        const identity = tickers.find((item) => String(item.ticker_name?.ticker_id || item.ticker_id || "").toUpperCase() === ticker.toUpperCase());
        const company = identity?.ticker_name?.company_name || identity?.company_name || ticker;
        return <button className="rebalance-target-chip" key={ticker} onClick={() => onTicker(ticker)}><TickerMark symbol={ticker} tickers={tickers}/><span className="rebalance-target-company"><b>{company}</b><small>{ticker}</small></span><strong>{percent(weight, 2)}</strong></button>;
      })}</div></section>}
      {row.pending && <section className="drawer-section"><h4>Target changes · {targets.length} held positions</h4><p className="muted">Projected at the latest stored portfolio value; order amounts can change with prices before execution.</p><div className="table-scroll"><table className="data-table rebalance-target-table"><thead><tr><th>Stock</th><th className="numeric">Target weight</th><th className="numeric">Target value</th><th className="numeric">Est. change</th><th>News link</th></tr></thead><tbody>{targets.map(([ticker, weight]) => { const ids = tickerEventMap[ticker] || []; const linked = linkedEvents.filter((event) => ids.includes(eventId(event)) || ids.includes(event.id)); const estimate = estimates.get(ticker); return <tr key={ticker}><td><button className="ticker-link" onClick={() => onTicker(ticker)}>{ticker}</button></td><td className="numeric">{percent(weight, 2)}</td><td className="numeric">{money(estimate?.value, currency)}</td><td className={`numeric ${estimate?.delta > 0 ? "positive" : estimate?.delta < 0 ? "negative" : ""}`}>{money(estimate?.delta || 0, currency)}</td><td>{linked.length ? linked.slice(0, 2).map((event) => <button className="drawer-inline-link" key={eventId(event)} onClick={() => onEvent(event)}>{cleanText(event.headline)}</button>) : ids.length ? ids.length + " linked stories" : "Strategy target"}</td></tr>; })}</tbody></table></div></section>}
      {linkedEvents.length > 0 && <section className="drawer-section"><h4>News attribution <span className="count-pill" style={{ marginLeft: 6 }}>{linkedEvents.length}</span></h4><div className="rebalance-news-list">{linkedEvents.map((event) => <button className="rebalance-news-card" key={eventId(event)} onClick={() => onEvent(event)}><b>{cleanText(event.headline)}</b><span className="marker-event-metadata"><span className="news-category-chip"><NewsCategoryIcon category={event.category}/>{event.category?.replaceAll("_", " ") || "News"}</span><span className="news-score-chip">{dateTime(eventTime(event))}</span><span className="news-score-chip">Sentiment <b>{event.sentiment?.score == null ? "—" : `${Number(event.sentiment.score) > 0 ? "+" : ""}${number(event.sentiment.score, 2)}`}</b></span><span className="news-score-chip">Impact <b>{impactScore(event.sentiment?.impact_score)}</b></span></span>{event.text && <small>{cleanText(event.text).slice(0, 260)}{cleanText(event.text).length > 260 ? "…" : ""}</small>}</button>)}</div></section>}
      {!linkedEvents.length && eventIds.length > 0 && <section className="drawer-section"><h4>News attribution</h4><p className="muted">{eventIds.length} event reference{eventIds.length === 1 ? "" : "s"} recorded with this decision; details are not in the currently loaded news page.</p></section>}
      {portfolio && <section className="drawer-section"><h4>Strategy trigger context</h4><div className="strategy-context-grid"><span>Strategy<b>{portfolio.news_enabled ? "News-aware" : "Scheduled / volume"}</b></span><span>Volume spike threshold<b>{portfolio.config?.volume_spike_ratio ? number(portfolio.config.volume_spike_ratio, 2) + "×" : "Not configured"}</b></span><span>Sentiment threshold<b>{portfolio.news_enabled && portfolio.config?.sentiment_delta_threshold != null ? number(portfolio.config.sentiment_delta_threshold, 2) : "Not applied"}</b></span><span>Target positions<b>{portfolio.config?.portfolio_size ?? row.targetCount ?? targets.length ?? "—"}</b></span></div></section>}
    </div>
  </Drawer>;
}

function TradeTable({ orders, currency, onTicker, events = [], onEvent }) {
  return <div className="table-scroll"><table className="data-table rebalance-trades-table"><thead><tr><th>Stock</th><th>Side</th><th className="numeric">Shares</th><th className="numeric">Execution</th><th className="numeric">Gross value</th><th className="numeric">Fees</th><th>News links</th></tr></thead><tbody>{orders.map((order) => {
    const ids = [...new Set([order.event_id, ...(order.event_ids || [])].filter(Boolean))];
    const linked = events.filter((event) => ids.includes(eventId(event)) || (!ids.length && (event.relevant_tickers || []).some((ticker) => (typeof ticker === "string" ? ticker : ticker.ticker_id) === order.ticker_id)));
    return <tr key={order.id}><td><button className="ticker-link" onClick={() => onTicker(order.ticker_id)}>{order.ticker_id}</button></td><td><span className={"side-badge " + order.side}>{order.side}</span></td><td className="numeric">{number(order.quantity, 0)}</td><td className="numeric">{money(order.price, currency)}</td><td className="numeric">{money(order.gross_value, currency)}</td><td className="numeric">{money(order.transaction_cost, currency)}</td><td>{linked.length ? <div className="rebalance-trade-news-links">{linked.map((event) => <button className="drawer-inline-link" key={eventId(event)} onClick={() => onEvent(event)}>{cleanText(event.headline)}</button>)}</div> : <span className="muted">No linked story</span>}</td></tr>;
  })}</tbody></table></div>;
}
