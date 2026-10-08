import { useCallback, useEffect, useState } from "react";
import { PriceHistoryChart } from "./LineChart";
import { WeightHistoryChart } from "./WeightHistoryChart";
import { Drawer, NewsCategoryIcon, PagePagination, SentimentMeter, TickerMark } from "./AppShell";
import { analysisStatus, affectedTickers, api, eventId, eventTime } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { changeClass, cleanText, dateTime, formatReason, impactScore, money, number, percent, timeAgo } from "../utils/format";
import { RebalanceDetailDrawer } from "./RebalanceDrawer";

export function EventDrawer({ event, portfolios, orders, pending, prices = {}, onClose, onTicker }) {
  const id = eventId(event);
  const loader = useCallback(async () => {
    const detail = id ? await api.event(id) : event;
    const symbols = affectedTickers(detail).slice(0, 5).map((item) => item.ticker_id);
    const results = await Promise.allSettled(symbols.map((symbol) => api.ticker(symbol, "3mo", "1d")));
    return { detail, charts: Object.fromEntries(symbols.map((symbol, index) => [symbol, results[index].status === "fulfilled" ? results[index].value.ticker_data || [] : []])) };
  }, [id, event]);
  const { data, loading, error } = usePolling(loader, 0, [loader]);
  const [storedActivity, setStoredActivity] = useState({ orders: [], rebalances: [] });
  useEffect(() => {
    let current = true;
    if (!id) { setStoredActivity({ orders: [], rebalances: [] }); return undefined; }
    api.eventActivity([id]).then((result) => {
      if (current) setStoredActivity({ orders: result.orders || [], rebalances: result.rebalances || [] });
    }).catch(() => { if (current) setStoredActivity({ orders: [], rebalances: [] }); });
    return () => { current = false; };
  }, [id]);
  const detail = data?.detail || event;
  const priceHistories = data?.charts || {};
  const symbols = affectedTickers(detail);
  const plans = [...new Map([
    ...Object.entries(pending || {}).flatMap(([portfolioId, items]) => items.filter((plan) => (plan.event_ids || []).includes(id) || Object.values(plan.ticker_event_ids || {}).flat().includes(id)).map((plan) => ({ ...plan, portfolioId }))),
    ...storedActivity.rebalances.filter((plan) => (plan.event_ids || []).includes(id) || Object.values(plan.ticker_event_ids || {}).flat().includes(id)).map((plan) => ({ ...plan, portfolioId: plan.portfolio_id })),
  ].map((plan) => [plan.id, plan])).values()];
  const allKnownOrders = [...new Map([...(orders || []), ...storedActivity.orders].map((order) => [order.id, order])).values()];
  const isDirectlyLinked = (order) => String(order.event_id || "") === String(id) || (order.event_ids || []).some((linkedId) => String(linkedId) === String(id));
  const planAttributedOrders = plans.filter((plan) => plan.status === "filled").flatMap((plan) => {
    const tickerEventMap = plan.ticker_event_ids || {};
    const attributedTickers = Object.entries(tickerEventMap).filter(([, ids]) => (ids || []).some((linkedId) => String(linkedId) === String(id))).map(([ticker]) => ticker.toUpperCase());
    const planLinksEvent = (plan.event_ids || []).some((linkedId) => String(linkedId) === String(id)) || attributedTickers.length > 0;
    if (!planLinksEvent) return [];
    const planTime = new Date(plan.executed_at || plan.scheduled_for || plan.decision_at || plan.created_at).getTime();
    return allKnownOrders.filter((order) => {
      if (isDirectlyLinked(order) || order.portfolio_id !== plan.portfolioId) return false;
      if (attributedTickers.length && !attributedTickers.includes(String(order.ticker_id || "").toUpperCase())) return false;
      const orderTime = new Date(order.executed_at || order.created_at).getTime();
      if (!Number.isFinite(planTime) || !Number.isFinite(orderTime) || Math.abs(orderTime - planTime) > 48 * 60 * 60 * 1000) return false;
      return String(order.reason || "").toLowerCase() === String(plan.reason || "").toLowerCase();
    });
  });
  const linkedOrders = [...new Map([...allKnownOrders.filter(isDirectlyLinked), ...planAttributedOrders].map((order) => [order.id, order])).values()];
  const actionablePlans = plans.filter((plan) => ["pending", "filled"].includes(plan.status));
  const mergedPlanId = plans.map((plan) => /merged into plan\s+([a-f\d]+)/i.exec(plan.last_error || "")?.[1]).find(Boolean);
  const mergedPlan = mergedPlanId ? storedActivity.rebalances.find((plan) => plan.id === mergedPlanId) : null;
  const modelReady = analysisStatus(detail) === "complete";
  return <Drawer title="Event brief" eyebrow="NEWS DETAIL" onClose={onClose}><div className="event-detail-content">{error && <p className="muted">Could not refresh event detail; showing the event from the feed.</p>}{loading && <p className="muted">Loading full event and stock histories…</p>}<h3>{cleanText(detail.headline)}</h3><div className="detail-meta event-detail-meta"><span>{dateTime(eventTime(detail))}</span><span>{detail.metadata?.source || detail.metadata?.provider || "News wire"}</span><span className="news-category-chip"><NewsCategoryIcon category={detail.category}/>{detail.category?.replaceAll("_", " ") || "Uncategorized"}</span></div>{detail.text && <p className="event-fulltext">{cleanText(detail.text)}</p>}{detail.url && <a className="button-secondary source-button" href={detail.url} target="_blank" rel="noreferrer">Open source story ↗</a>}<section className="drawer-section"><h4>Model analysis</h4><div className="drawer-score-row"><SentimentMeter score={modelReady ? detail.sentiment?.score : null}/><span>Impact <b>{!modelReady ? "Pending" : impactScore(detail.sentiment?.impact_score)}</b></span>{analysisStatus(detail) !== "complete" && <span>Status <b>{analysisStatus(detail).replaceAll("_", " ")}</b></span>}</div><p className="muted">Sentiment describes the model’s reading of this story. It is not a forecast of price movement.</p></section><section className="drawer-section"><h4>Affected stocks</h4>{symbols.length ? <><div className="table-scroll event-stock-table-wrap"><table className="data-table event-stock-table"><thead><tr><th>Stock</th><th>Shares held</th><th className="numeric">Relevance</th><th className="numeric">Price</th><th className="numeric">Day</th></tr></thead><tbody>{symbols.slice(0, 5).map((item) => { const bars = priceHistories[item.ticker_id] || [], last = bars.at(-1), prev = bars.at(-2), change = last && prev ? (last.close / prev.close - 1) * 100 : null, held = (portfolios || []).map((portfolio) => ({ portfolio, position: (portfolio.positions || []).find((position) => String(position.ticker_id).toUpperCase() === String(item.ticker_id).toUpperCase()) })).filter(({ position }) => Number(position?.shares) > 0); return <tr key={item.ticker_id}><td><button className="ticker-link" onClick={() => onTicker(item.ticker_id)}>{item.ticker_id}</button></td><td>{held.length ? <div className="event-holding-list">{held.map(({ portfolio, position }) => <span className="event-holding-chip" key={portfolio.id}><b>{portfolio.news_enabled ? "News-aware" : "Normal"}</b>{number(position.shares, 0)}</span>)}</div> : <span className="muted">Not held</span>}</td><td className="numeric">{number(item.relevance_score, 2)}</td><td className="numeric">{last ? money(last.close) : "—"}</td><td className={`numeric ${changeClass(change)}`}>{percent(change, 2, false)}</td></tr>; })}</tbody></table></div>{symbols.slice(0, 5).map((item) => { const bars = (priceHistories[item.ticker_id] || []).filter((bar) => Number.isFinite(Number(bar.close))); if (bars.length < 2) return null; const publishedAt = new Date(eventTime(detail)).getTime(), eventIndex = bars.reduce((best, bar, index) => Math.abs(new Date(bar.timestamp).getTime() - publishedAt) < Math.abs(new Date(bars[best]?.timestamp).getTime() - publishedAt) ? index : best, 0), after = bars[Math.min(eventIndex + 2, bars.length - 1)], observed = bars[eventIndex]?.close ? (after.close / bars[eventIndex].close - 1) * 100 : null; return <div className="event-stock-chart" key={`chart-${item.ticker_id}`}><h5>{item.ticker_id} around the event</h5><PriceHistoryChart bars={bars} markers={[{ id, index: eventIndex, kind: "event", label: `News published ${dateTime(eventTime(detail))}` }]} height={210}/><p>Observed {percent(observed, 2, false)} in the two sessions after the event. This shows movement after the news, not proof that the news caused it.</p></div>; })}</> : <p className="muted">No affected tickers have been identified.</p>}</section><EventPortfolioActions linkedOrders={linkedOrders} plans={actionablePlans} portfolios={portfolios} prices={prices} mergedPlanId={mergedPlanId} mergedPlan={mergedPlan} allPlans={plans}/></div></Drawer>;
}

function EventPortfolioActions({ linkedOrders, plans, portfolios, prices, mergedPlanId, mergedPlan, allPlans }) {
  const estimatedTrades = plans.filter((plan) => plan.status === "pending").flatMap((plan) => {
    const portfolio = portfolios.find((item) => String(item.id) === String(plan.portfolioId || plan.portfolio_id));
    return pendingTradePreview(plan, portfolio, prices).map((trade) => ({ ...trade, plan, portfolio }));
  });
  const hasRows = linkedOrders.length || estimatedTrades.length || plans.length;
  return <section className="drawer-section"><h4>Portfolio actions</h4>{hasRows ? <><div className="table-scroll"><table className="data-table event-portfolio-actions"><thead><tr><th>Action</th><th>Stock</th><th>Shares</th><th className="numeric">Value (est. if pending)</th><th>Portfolio / date</th></tr></thead><tbody>{linkedOrders.map((order) => <tr key={`order-${order.id}`}><td><span className={`side-badge ${String(order.side).toLowerCase()}`}>{String(order.side).toUpperCase()}</span></td><td>{order.ticker_id}</td><td>{number(order.quantity, 0)}</td><td className="numeric">{money(order.gross_value)}</td><td>{portfolios.find((portfolio) => String(portfolio.id) === String(order.portfolio_id))?.name || "Paper portfolio"}<small className="table-subtext">{dateTime(order.created_at)}</small></td></tr>)}{estimatedTrades.map(({ plan, portfolio, ticker, side, shares, price, value }) => <tr key={`estimate-${plan.id}-${ticker}`}><td><span className={`side-badge ${side}`}>{side.toUpperCase()}</span></td><td>{ticker}</td><td>~{number(shares, 0)}</td><td className="numeric">{price > 0 ? `~${money(value, portfolio?.currency || "USD")}` : "Price unavailable"}</td><td>{portfolio?.name || "Paper portfolio"}<small className="table-subtext">Scheduled {dateTime(plan.scheduled_for)} · {formatReason(plan.reason)}</small></td></tr>)}{plans.filter((plan) => plan.status === "pending" && !estimatedTrades.some((trade) => trade.plan.id === plan.id)).map((plan) => { const targetStocks = Object.keys(plan.target_weights || {}).map((ticker) => ticker.toUpperCase()); return <tr key={`pending-${plan.id}`}><td><span className="status-pill pending">Pending</span></td><td>{targetStocks.length ? targetStocks.join(", ") : "Targets unavailable"}</td><td colSpan="2" className="muted">No share change estimated at current reference prices</td><td>{portfolios.find((portfolio) => String(portfolio.id) === String(plan.portfolioId || plan.portfolio_id))?.name || "Paper portfolio"}<small className="table-subtext">Scheduled {dateTime(plan.scheduled_for)} · {formatReason(plan.reason)}</small></td></tr>; })}{plans.filter((plan) => plan.status !== "pending").map((plan) => <tr key={`plan-${plan.id}`}><td>Rebalance executed</td><td>—</td><td>—</td><td className="numeric">—</td><td>{portfolios.find((portfolio) => String(portfolio.id) === String(plan.portfolioId || plan.portfolio_id))?.name || "Paper portfolio"}<small className="table-subtext">{dateTime(plan.executed_at || plan.scheduled_for)} · {formatReason(plan.reason)}</small></td></tr>)}</tbody></table></div>{plans.some((plan) => plan.status === "pending") && <p className="pending-event-estimate-note">Pending quantities and values are estimates at current reference prices; they may change before execution.</p>}</> : mergedPlanId ? <div className="linked-record"><b>{mergedPlan?.status === "pending" ? "Included in a consolidated rebalance" : "Decision merged into another plan"}</b><span>{mergedPlan ? `${dateTime(mergedPlan.scheduled_for)} · ${formatReason(mergedPlan.reason)}` : "The source decision was merged into the session plan."}</span><small>{portfolios.find((portfolio) => String(portfolio.id) === String(mergedPlan?.portfolio_id || allPlans[0]?.portfolioId))?.name || "Paper portfolio"}</small></div> : <p className="muted">No portfolio action is linked to this event in the stored records.</p>}</section>;
}

function pendingTradePreview(plan, portfolio, prices) {
  const positions = Array.isArray(portfolio?.positions) ? portfolio.positions : [];
  const current = new Map(positions.map((position) => [String(position.ticker_id || "").toUpperCase(), position]));
  const targets = Object.fromEntries(Object.entries(plan?.target_weights || {}).map(([ticker, weight]) => [ticker.toUpperCase(), Number(weight) || 0]));
  const targetTotal = Object.values(targets).reduce((sum, weight) => sum + weight, 0);
  if (String(plan?.reason || "").toLowerCase().includes("news") && targetTotal > 1) for (const ticker of Object.keys(targets)) targets[ticker] /= targetTotal;
  const tickers = [...new Set([...current.keys(), ...Object.keys(targets)])];
  const marks = new Map(tickers.map((ticker) => [ticker, Number(prices?.[ticker]?.price || current.get(ticker)?.last_price) || 0]));
  const equity = Math.max(0, Number(portfolio?.cash) || 0) + positions.reduce((sum, position) => sum + (Number(position.shares) || 0) * (marks.get(String(position.ticker_id || "").toUpperCase()) || 0), 0);
  return tickers.map((ticker) => {
    const price = marks.get(ticker) || 0;
    const held = Number(current.get(ticker)?.shares) || 0;
    const desired = price > 0 ? Math.floor((targets[ticker] || 0) * equity / price) : held;
    const delta = desired - held;
    return { ticker, side: delta >= 0 ? "buy" : "sell", shares: Math.abs(delta), price, value: Math.abs(delta) * price };
  }).filter((trade) => trade.shares > 0).sort((a, b) => (a.side === "sell" ? 0 : 1) - (b.side === "sell" ? 0 : 1) || a.ticker.localeCompare(b.ticker));
}

export function OrderDetailDrawer({ order, portfolios = [], events = [], tickers = [], onClose, onEvent, onTicker }) {
  const ids = [...new Set([order.event_id, ...(order.event_ids || [])].filter(Boolean))];
  const [linkedEvents, setLinkedEvents] = useState(() => ids.map((id) => events.find((item) => eventId(item) === id)).filter(Boolean));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const known = new Map(events.map((event) => [eventId(event), event]));
    const missing = ids.filter((id) => !known.has(id));
    setLinkedEvents(ids.map((id) => known.get(id)).filter(Boolean));
    if (!missing.length) return () => { active = false; };
    setLoading(true); setError("");
    Promise.allSettled(missing.map((id) => api.event(id))).then((results) => {
      if (!active) return;
      const fetched = results.filter((result) => result.status === "fulfilled").map((result) => result.value);
      setLinkedEvents(ids.map((id) => known.get(id) || fetched.find((event) => eventId(event) === id)).filter(Boolean));
      if (fetched.length < missing.length) setError("Some linked news records could not be loaded.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [order.id, ids.join(","), events]);
  const orderTicker = String(order.ticker_id || "").toUpperCase();
  const sortedLinkedEvents = [...linkedEvents].sort((a, b) => {
    const relevance = (event) => affectedTickers(event).find((ticker) => String(ticker.ticker_id).toUpperCase() === orderTicker)?.relevance_score;
    return (Number(relevance(b)) || 0) - (Number(relevance(a)) || 0) || new Date(eventTime(b)).getTime() - new Date(eventTime(a)).getTime();
  });
  const portfolio = portfolios.find((item) => item.id === order.portfolio_id);
  const currency = portfolio?.currency || "USD";
  const cashDelta = order.net_cash_change;
  return <Drawer title={`${order.side?.toUpperCase() || "ORDER"} ${order.ticker_id}`} eyebrow="PAPER ORDER DETAIL" onClose={onClose}>
    <div className="order-detail-drawer">
      <div className={`order-detail-hero ${order.side}`}><span className="order-detail-side">{order.side?.toUpperCase()} · EXECUTED</span><h3>{number(order.quantity, 0)} shares of <button className="ticker-link order-ticker" onClick={() => onTicker(order.ticker_id)}><TickerMark symbol={order.ticker_id} tickers={tickers}/>{order.ticker_id}</button></h3><p>{portfolio?.name || "Paper portfolio"} · {dateTime(order.created_at)}</p></div>
      <section className="drawer-section"><h4>Execution</h4><div className="order-detail-metrics"><div><span>Execution price</span><b>{money(order.price, currency)}</b></div><div><span>Gross value</span><b>{money(order.gross_value, currency)}</b></div><div><span>Transaction fees</span><b>{money(order.transaction_cost, currency)}</b></div><div><span>Net cash change</span><b className={Number(cashDelta) < 0 ? "negative" : "positive"}>{cashDelta == null ? "—" : money(cashDelta, currency)}</b></div></div><div className="order-detail-meta"><span>Reason <b>{formatReason(order.reason || "Manual order")}</b></span><span>Order ID <code>{order.id}</code></span></div></section>
      <section className="drawer-section"><h4>News behind this order <span className="count-pill">{ids.length}</span></h4>{loading && <p className="muted">Loading linked news…</p>}{error && <p className="muted">{error}</p>}{sortedLinkedEvents.length ? <div className="rebalance-news-list order-linked-news">{sortedLinkedEvents.map((event) => <button className="rebalance-news-card order-news-card" key={eventId(event)} onClick={() => onEvent(event)}><b>{cleanText(event.headline)}</b><span className="marker-event-metadata"><span className="news-category-chip"><NewsCategoryIcon category={event.category}/>{event.category?.replaceAll("_", " ") || "Market news"}</span><span className="news-score-chip">{dateTime(eventTime(event))}</span><span className="news-score-chip">Sentiment <b>{event.sentiment?.score == null ? "—" : `${Number(event.sentiment.score) > 0 ? "+" : ""}${number(event.sentiment.score, 2)}`}</b></span><span className="news-score-chip">Impact <b>{impactScore(event.sentiment?.impact_score)}</b></span></span>{event.text && <small>{cleanText(event.text).slice(0, 260)}{cleanText(event.text).length > 260 ? "…" : ""}</small>}<span className="linked-event-tickers">{affectedTickers(event).map((ticker) => <i key={ticker.ticker_id} onClick={(e) => { e.stopPropagation(); onTicker(ticker.ticker_id); }}>{ticker.ticker_id} · relevance {number(ticker.relevance_score, 2)}</i>)}</span></button>)}</div> : !loading && <p className="muted">No linked news event IDs are stored on this order.</p>}</section>
    </div>
  </Drawer>;
}

export function PortfolioMarkerDrawer({ marker, portfolios = [], events: availableEvents = [], tickers = [], currency = "USD", onClose, onEvent, onTicker }) {
  if (marker.kind === "rebalance") return <RebalanceDetailDrawer row={marker} portfolios={portfolios} events={availableEvents} tickers={tickers} onClose={onClose} onEvent={onEvent} onTicker={onTicker}/>;
  const events = marker.events || [];
  const orders = marker.orders || [];
  const isNews = marker.kind === "event";
  return <Drawer title={isNews ? "News at this point" : "Rebalance trades"} eyebrow={isNews ? "PORTFOLIO NEWS MARKER" : "PORTFOLIO ACTIVITY MARKER"} onClose={onClose}>
    <div className="marker-detail-content"><p className="detail-meta">{dateTime(marker.timestamp)} · {marker.label}</p>
      {events.length > 0 && <section className="drawer-section"><h4>{events.length === 1 ? "Linked news event" : `${events.length} news events on this session`}</h4><div className="marker-event-list">{events.map((event) => <button className="marker-event-link" key={eventId(event)} onClick={() => onEvent(event)}><b>{cleanText(event.headline)}</b><span className="marker-event-metadata"><span>{dateTime(eventTime(event))}</span><span className="news-category-chip"><NewsCategoryIcon category={event.category}/>{event.category?.replaceAll("_", " ") || "News"}</span><span className="news-score-chip">Sentiment <b>{event.sentiment?.score == null ? "—" : `${Number(event.sentiment.score) > 0 ? "+" : ""}${number(event.sentiment.score, 2)}`}</b></span><span className="news-score-chip">Impact <b>{impactScore(event.sentiment?.impact_score)}</b></span></span></button>)}</div></section>}
      {orders.length > 0 && <section className="drawer-section"><h4>{formatReason(marker.reason || "Rebalance")} · {orders.length} trades</h4><div className="table-scroll"><table className="data-table"><thead><tr><th>Stock</th><th>Side</th><th className="numeric">Shares</th><th className="numeric">Price</th><th className="numeric">Value (est. if pending)</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td><button className="ticker-link" onClick={() => onTicker(order.ticker_id)}>{order.ticker_id}</button></td><td>{order.side}</td><td className="numeric">{number(order.quantity, 0)}</td><td className="numeric">{money(order.price, currency)}</td><td className="numeric">{money(order.gross_value, currency)}</td></tr>)}</tbody></table></div><p className="muted">Values are recorded paper executions for the selected strategy.</p></section>}
      {!events.length && !orders.length && <p className="muted">No matching news or executed trades were returned for this marker.</p>}
    </div>
  </Drawer>;
}

export function StockDrawer({ symbol, portfolios, orders, tickers = [], onClose, onEvent }) {
  const [transactionPage, setTransactionPage] = useState(1);
  const [relatedNewsPage, setRelatedNewsPage] = useState(1);
  const [relatedNewsPageCache, setRelatedNewsPageCache] = useState({});
  const [relatedNewsLoading, setRelatedNewsLoading] = useState(false);
  const [relatedNewsError, setRelatedNewsError] = useState("");
  const [priceChartView, setPriceChartView] = useState("line");
  const [transactionOrders, setTransactionOrders] = useState([]);
  const [transactionTotal, setTransactionTotal] = useState(0);
  const [transactionLoading, setTransactionLoading] = useState(false);
  const [selectedPortfolioId, setSelectedPortfolioId] = useState("");
  const transactionPageSize = 20;
  const relatedNewsPageSize = 5;
  const relatedNewsInitialSize = 20;
  const loader = useCallback(async () => {
    const [stock, news] = await Promise.allSettled([api.ticker(symbol, "3mo", "1d"), api.tickerEvents(symbol, { limit: 20 })]);
    return { stock: stock.status === "fulfilled" ? stock.value : null, news: news.status === "fulfilled" ? news.value.events || [] : [], newsTotal: news.status === "fulfilled" ? news.value.total_count || 0 : 0, error: stock.status === "rejected" ? stock.reason.message : "" };
  }, [symbol]);
  const { data, loading, error } = usePolling(loader, 0, [loader]);
  useEffect(() => {
    setRelatedNewsPage(1);
    setRelatedNewsPageCache({});
    setRelatedNewsError("");
  }, [symbol]);
  const stock = data?.stock;
  const selectedPortfolio = selectedPortfolioId === "all" ? null : portfolios.find((portfolio) => portfolio.id === selectedPortfolioId) || portfolios.find((portfolio) => (portfolio.positions || []).some((position) => position.ticker_id === symbol)) || portfolios[0];
  const position = selectedPortfolio?.positions?.find((item) => item.ticker_id === symbol);
  const historyPortfolioIds = selectedPortfolio?.id ? [selectedPortfolio.id] : portfolios.map((portfolio) => portfolio.id).filter(Boolean);
  const historyPortfolioKey = historyPortfolioIds.join(",");
  const transactionPages = Math.max(1, Math.ceil(transactionTotal / transactionPageSize));
  const transactionRows = transactionOrders.slice((transactionPage - 1) * transactionPageSize, transactionPage * transactionPageSize);
  const loadTransactionPage = useCallback(async (requestedPage) => {
    setTransactionLoading(true);
    try {
      const limit = requestedPage * transactionPageSize;
      const results = await Promise.allSettled(historyPortfolioIds.map((id) => api.orders(id, limit, 0, symbol)));
      const completed = results.filter((result) => result.status === "fulfilled").map((result) => result.value);
      const rows = [...new Map(completed.flatMap((result) => result.orders || []).map((order) => [order.id, order])).values()]
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
      setTransactionOrders(rows);
      setTransactionTotal(completed.reduce((total, result) => total + (Number(result.total_count) || 0), 0));
      setTransactionPage(requestedPage);
    } finally {
      setTransactionLoading(false);
    }
  }, [historyPortfolioKey, symbol]);
  useEffect(() => {
    setTransactionPage(1);
    setTransactionOrders([]);
    setTransactionTotal(0);
    loadTransactionPage(1);
  }, [loadTransactionPage]);
  const changeTransactionPage = (page) => {
    if (page < 1 || page > transactionPages || transactionLoading) return;
    if (transactionOrders.length >= page * transactionPageSize) setTransactionPage(page);
    else loadTransactionPage(page);
  };
  const bars = stock?.ticker_data || [];
  const chartMarkers = (data?.news || []).map((event) => {
    const at = new Date(eventTime(event)).getTime();
    const index = bars.reduce((best, bar, i) => Math.abs(new Date(bar.timestamp).getTime() - at) < Math.abs(new Date(bars[best]?.timestamp).getTime() - at) ? i : best, 0);
    return { id: eventId(event), index, kind: "event", label: event.headline };
  });
  const currency = selectedPortfolio?.currency || "USD";
  const latest = bars.at(-1), previous = bars.at(-2);
  const dayChange = latest?.close && previous?.close ? (latest.close / previous.close - 1) * 100 : null;
  const companyName = stock?.ticker_name?.company_name || symbol;
  const relatedNews = (data?.news || []).filter((event) => analysisStatus(event) === "complete");
  const relatedNewsTotal = Number(data?.newsTotal) || relatedNews.length;
  const relatedNewsPages = Math.max(1, Math.ceil(relatedNewsTotal / relatedNewsPageSize));
  const relatedNewsVisible = relatedNewsPage <= Math.ceil(relatedNewsInitialSize / relatedNewsPageSize)
    ? relatedNews.slice((relatedNewsPage - 1) * relatedNewsPageSize, relatedNewsPage * relatedNewsPageSize)
    : relatedNewsPageCache[relatedNewsPage] || [];
  const changeRelatedNewsPage = async (page) => {
    if (page < 1 || page > relatedNewsPages || relatedNewsLoading) return;
    const offset = (page - 1) * relatedNewsPageSize;
    if (offset >= relatedNewsInitialSize && !relatedNewsPageCache[page]) {
      setRelatedNewsLoading(true);
      try {
        const result = await api.tickerEvents(symbol, { limit: relatedNewsPageSize, offset });
        setRelatedNewsPageCache((current) => ({ ...current, [page]: result.events || [] }));
        setRelatedNewsError("");
      } catch (requestError) {
        setRelatedNewsError(requestError.message || "Could not load this news page.");
        return;
      } finally {
        setRelatedNewsLoading(false);
      }
    }
    setRelatedNewsPage(page);
  };
  const heldPositions = portfolios.map((portfolio) => ({ portfolio, position: (portfolio.positions || []).find((item) => String(item.ticker_id).toUpperCase() === String(symbol).toUpperCase()) })).filter(({ position }) => Number(position?.shares) > 0);

  return <Drawer title="Stock details" eyebrow="SECURITY PROFILE" onClose={onClose}>
    <div className="stock-detail-content">
      {(loading || error || data?.error) && <p className={error || data?.error ? "drawer-error" : "muted"}>{error || data?.error || "Loading stock profile and recent news…"}</p>}
      <div className="stock-detail-title">
        <h3><TickerMark symbol={symbol} tickers={tickers}/>{symbol}<span>{companyName}</span></h3>
        <div><b>{latest?.close ? money(latest.close, currency) : "—"}</b><span className={changeClass(dayChange)}>{percent(dayChange, 2, false)}</span></div>
        <small>Price history from the connected market-data source · {bars.length ? `${bars.length} sessions loaded` : "No recent price history available"}</small>
      </div>
      {bars.length > 1 && <section className="drawer-section stock-chart-section"><div className="stock-section-heading"><h4>Price history</h4><span>3 months · daily</span></div><PriceHistoryChart bars={bars} markers={chartMarkers} height={220} onViewChange={setPriceChartView}/></section>}
      {selectedPortfolio && <section className="drawer-section stock-weight-section"><div className="stock-section-heading"><h4>{symbol} portfolio weight</h4><span>{selectedPortfolio.news_enabled ? "News-aware" : "Normal strategy"}</span></div><WeightHistoryChart metrics={selectedPortfolio.daily_metrics} symbol={symbol} height={235} newsEnabled={selectedPortfolio.news_enabled} portfolios={portfolios} activePortfolioId={selectedPortfolio.id}/></section>}
      <section className={`drawer-section ${priceChartView === "line" ? "stock-chart-after-line" : ""}`}><div className="stock-section-heading"><h4>Portfolio position</h4><span>{heldPositions.length} portfolio{heldPositions.length === 1 ? "" : "s"}</span></div>{heldPositions.length ? <div className="stock-position-cards">{heldPositions.map(({ portfolio, position: held }) => <article className="stock-position-card" key={portfolio.id}><header><span className="ticker-cell"><TickerMark symbol={symbol} tickers={tickers}/><span><b>{portfolio.name}</b><small>{portfolio.news_enabled ? "News-aware portfolio" : "Normal strategy portfolio"}</small></span></span><span className="stock-position-type">{portfolio.news_enabled ? "NEWS" : "NORMAL"}</span></header><div className="stock-position-metrics"><div><small>Shares held</small><b>{number(held.shares, 0)}</b></div><div><small>Portfolio weight</small><b>{percent(held.weight, 2)}</b></div><div><small>Market value</small><b>{money(held.market_value, portfolio.currency || "USD")}</b></div><div><small>Unrealized P&amp;L</small><b className={changeClass(held.unrealized_pnl)}>{money(held.unrealized_pnl, portfolio.currency || "USD")}</b></div></div></article>)}</div> : <p className="muted">This stock is not currently held in the available portfolios.</p>}</section>
      <section className="drawer-section"><div className="stock-section-heading"><h4>Related news</h4><span>{relatedNewsTotal.toLocaleString()} analyzed</span></div>{relatedNewsTotal ? <><div className="stock-related-news">{relatedNewsVisible.map((event) => {
        const relevance = affectedTickers(event).find((item) => String(item.ticker_id).toUpperCase() === String(symbol).toUpperCase())?.relevance_score;
        const sentiment = event.sentiment?.score;
        const impact = event.sentiment?.impact_score;
        return <button className="related-event-button" key={eventId(event)} onClick={() => onEvent(event)}>
          <span className="related-event-meta"><span className="news-category-chip"><NewsCategoryIcon category={event.category}/>{event.category?.replaceAll("_", " ") || "News"}</span><span className="related-event-source">{event.metadata?.source || event.metadata?.provider || "News wire"}</span><time>{dateTime(eventTime(event))} · {timeAgo(eventTime(event))}</time></span>
          <b>{cleanText(event.headline)}</b>
          {event.text && <span className="related-event-summary">{cleanText(event.text).slice(0, 280)}{cleanText(event.text).length > 280 ? "…" : ""}</span>}
          <span className="related-score-grid">
            <span className={`related-score sentiment ${Number(sentiment) < 0 ? "negative" : Number(sentiment) > 0 ? "positive" : ""}`}><small>Sentiment</small><b>{sentiment == null ? "—" : `${Number(sentiment) > 0 ? "+" : ""}${number(sentiment, 2)}`}</b></span>
            <span className="related-score"><small>Stock relevance</small><b>{relevance == null ? "—" : number(relevance, 2)}</b></span>
            <span className="related-score impact"><small>News impact</small><b>{impactScore(impact)}</b></span>
          </span>
        </button>;
      })}</div>{relatedNewsError && <p className="drawer-error">{relatedNewsError}</p>}<PagePagination page={relatedNewsPage} totalPages={relatedNewsPages} hasMore={relatedNewsPage < relatedNewsPages} onPage={changeRelatedNewsPage} loading={relatedNewsLoading}/></> : <p className="muted">No analyzed news is currently linked to {symbol}.</p>}</section>
      <section className="drawer-section"><div className="stock-section-heading"><h4>Purchase and sale history</h4><span>{transactionTotal} matching order{transactionTotal === 1 ? "" : "s"}</span></div><div className="filter-bar stock-portfolio-filter"><label>Portfolio<select value={selectedPortfolio?.id || "all"} onChange={(event) => setSelectedPortfolioId(event.target.value)}><option value="all">All portfolios</option>{portfolios.map((portfolio) => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label></div>{transactionLoading && !transactionOrders.length ? <p className="muted">Loading stock orders…</p> : transactionRows.length ? <div className="table-scroll"><table className="data-table stock-transaction-table"><thead><tr><th>Date</th><th>Side</th><th className="numeric">Shares</th><th className="numeric">Execution</th><th>Reason</th></tr></thead><tbody>{transactionRows.map((order) => <tr key={order.id}><td>{dateTime(order.created_at)}</td><td><span className={`side-badge ${order.side}`}>{order.side}</span></td><td className="numeric">{number(order.quantity, 0)}</td><td className="numeric">{money(order.price, currency)}</td><td>{formatReason(order.reason || "Manual")}</td></tr>)}</tbody></table></div> : <p className="muted">No purchase or sale records are loaded for this stock.</p>}{transactionTotal > 0 && <PagePagination page={transactionPage} totalPages={transactionPages} hasMore={transactionPage < transactionPages} onPage={changeTransactionPage} loading={transactionLoading}/>}</section>
    </div>
  </Drawer>;
}
