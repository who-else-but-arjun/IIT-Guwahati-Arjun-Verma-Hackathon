import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { DataNotice, PageHeading, PagePagination, Skeleton, TickerMark } from "../components/AppShell";
import { changeClass, dateTime, formatReason, money, number, percent } from "../utils/format";

const PAGE_SIZE = 25;

export function OrdersPage({ portfolios = [], data = {}, pending = {}, prices = {}, quoteLoading = false, tickers = [], loading, error, refresh, initialTicker = "", onTicker, onOrder, onLoadMore, loadingMore }) {
  const [portfolioId, setPortfolioId] = useState("");
  const [side, setSide] = useState("");
  const [tickerFilter, setTickerFilter] = useState("");
  const [page, setPage] = useState(1);
  const [queuedPage, setQueuedPage] = useState(null);
  const [orderForm, setOrderForm] = useState(false);
  const [form, setForm] = useState({ ticker_id: initialTicker, side: "buy", quantity: "" });
  const [quote, setQuote] = useState(null), [quoteError, setQuoteError] = useState("");
  const [submitting, setSubmitting] = useState(false), [message, setMessage] = useState("");
  useEffect(() => { if (initialTicker) setForm((current) => ({ ...current, ticker_id: initialTicker })); }, [initialTicker]);
  const allOrders = Object.values(data).flatMap((result) => result?.orders || []).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const pendingOrders = useMemo(() => Object.entries(pending).flatMap(([portfolioId, plans]) => {
    const portfolio = portfolios.find((item) => String(item.id) === String(portfolioId));
    const positions = portfolio?.positions || [];
    const current = new Map(positions.map((position) => [String(position.ticker_id || "").toUpperCase(), position]));
    return (plans || []).filter((plan) => plan.status === "pending").flatMap((plan) => {
      const targets = Object.fromEntries(Object.entries(plan.target_weights || {}).map(([ticker, weight]) => [ticker.toUpperCase(), Number(weight) || 0]));
      const total = Object.values(targets).reduce((sum, weight) => sum + weight, 0);
      if (String(plan.reason || "").toLowerCase().includes("news") && total > 1) for (const ticker of Object.keys(targets)) targets[ticker] /= total;
      const symbols = [...new Set([...current.keys(), ...Object.keys(targets)])];
      const marks = new Map(symbols.map((ticker) => [ticker, Number(prices?.[ticker]?.price || current.get(ticker)?.last_price) || 0]));
      const equity = Math.max(0, Number(portfolio?.cash) || 0) + positions.reduce((sum, position) => sum + (Number(position.shares) || 0) * (marks.get(String(position.ticker_id || "").toUpperCase()) || 0), 0);
      const trades = symbols.map((ticker) => {
        const price = marks.get(ticker) || 0;
        const held = Number(current.get(ticker)?.shares) || 0;
        const desired = price > 0 ? Math.floor((targets[ticker] || 0) * equity / price) : held;
        const delta = desired - held;
        return { ticker, side: delta >= 0 ? "buy" : "sell", quantity: Math.abs(delta), price, gross_value: Math.abs(delta) * price };
      }).filter((trade) => trade.quantity > 0).sort((a, b) => (a.side === "sell" ? 0 : 1) - (b.side === "sell" ? 0 : 1) || a.ticker.localeCompare(b.ticker));
      return trades.map((trade) => ({ ...trade, ticker_id: trade.ticker, id: `pending-${plan.id}-${trade.ticker}`, portfolio_id: portfolioId, created_at: plan.decision_at || plan.created_at || plan.scheduled_for, scheduled_for: plan.scheduled_for, reason: plan.reason, status: "pending", isPending: true, transaction_cost: trade.gross_value * (Number(portfolio?.config?.transaction_cost) || 0), event_ids: plan.ticker_event_ids?.[trade.ticker] || plan.event_ids || [], plan }));
    });
  }), [pending, portfolios, prices]);
  const allRows = [...allOrders, ...pendingOrders].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const totalOrders = Object.values(data).reduce((total, result) => total + (result?.orderCount || 0), 0);
  const hasMoreOrders = Object.values(data).some((result) => result?.hasMoreOrders);
  const rows = useMemo(() => allRows.filter((order) => (!portfolioId || String(order.portfolio_id) === String(portfolioId)) && (!side || order.side === side) && (!tickerFilter || String(order.ticker_id || "").toLowerCase().includes(tickerFilter.trim().toLowerCase()))), [allRows, portfolioId, side, tickerFilter]);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  useEffect(() => {
    if (queuedPage != null && queuedPage <= totalPages) { setPage(queuedPage); setQueuedPage(null); }
    else if (queuedPage != null && !hasMoreOrders) { setPage(totalPages); setQueuedPage(null); }
    else setPage((current) => Math.min(current, totalPages));
  }, [queuedPage, totalPages, hasMoreOrders]);
  const selected = portfolios.find((p) => p.id === portfolioId) || portfolios.find((p) => p.status === "active") || portfolios[0];
  const currentPortfolio = selected && (data[selected.id]?.portfolio || selected);
  const estimatedGross = quote && Number(form.quantity) > 0 ? quote.price * Number(form.quantity) : 0;
  const estimatedFee = estimatedGross * Number(currentPortfolio?.config?.transaction_cost || 0);
  const setFilter = (setter) => (event) => { setter(event.target.value); setPage(1); setQueuedPage(null); };
  const changePage = (next) => {
    if (next <= totalPages) { setPage(next); setQueuedPage(null); return; }
    if (hasMoreOrders) { setQueuedPage(next); if (!loadingMore) onLoadMore?.(); }
  };
  const priceLookup = async () => {
    const ticker = form.ticker_id.trim().toUpperCase();
    if (!ticker) { setQuote(null); setQuoteError(""); return; }
    try { setQuoteError(""); const result = await api.ticker(ticker, "5d", "1d"); const bars = result.ticker_data || []; const latest = bars.at(-1), previous = bars.at(-2); if (!latest?.close) throw new Error("No recent price was returned for this ticker."); setQuote({ price: latest.close, change: previous?.close ? (latest.close / previous.close - 1) * 100 : null, company: result.ticker_name?.company_name || ticker, currency: "USD" }); }
    catch (err) { setQuote(null); setQuoteError(err.message); }
  };
  const openForm = () => { setForm({ ticker_id: initialTicker || "", side: "buy", quantity: "" }); setQuote(null); setQuoteError(""); setMessage(""); setOrderForm(true); };
  const submit = async (event) => {
    event.preventDefault(); if (!selected || !form.ticker_id || !form.quantity) return;
    setSubmitting(true); setMessage("");
    try { await api.placeOrder(selected.id, { ticker_id: form.ticker_id, side: form.side, quantity: Number(form.quantity), reason: "manual" }); setMessage("Paper order placed successfully."); setOrderForm(false); await refresh(); }
    catch (err) { setMessage(err.message); }
    finally { setSubmitting(false); }
  };
  return <>
    <PageHeading kicker="SIMULATED EXECUTION" title="Orders" description="Paper orders recorded for your portfolios, with a simple manual execution ticket." actions={<span className="paper-pill">PAPER TRADING ONLY</span>} />
    {message && <div className={`inline-alert ${message.includes("successfully") ? "success" : "error"}`}>{message}<button onClick={() => setMessage("")} aria-label="Dismiss">×</button></div>}
    <section className="panel order-panel"><div className="table-heading"><div><h2>Order history</h2><p>{pendingOrders.length ? `${pendingOrders.length} pending rebalance orders · ` : ""}{totalOrders.toLocaleString()} stored executions · newest first</p></div></div>
      <div className="filter-bar table-filters order-filters"><label className="filter-search"><span>⌕</span><input value={tickerFilter} onChange={setFilter(setTickerFilter)} placeholder="Search ticker" aria-label="Search ticker"/></label><select value={portfolioId} onChange={setFilter(setPortfolioId)} aria-label="Filter by portfolio"><option value="">All portfolios</option>{portfolios.map((portfolio) => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select><select value={side} onChange={setFilter(setSide)} aria-label="Filter by side"><option value="">All sides</option><option value="buy">Buy</option><option value="sell">Sell</option></select><button className="button-primary" onClick={openForm} disabled={!portfolios.length}>＋ New paper order</button><button className="icon-button refresh-button" onClick={refresh} aria-label="Refresh orders">↻</button></div>
      <DataNotice skeleton="table" loading={loading && !allRows.length} error={error} onRetry={refresh} empty={!pageRows.length && !hasMoreOrders ? "No paper orders match these filters." : null}><div className="table-scroll order-table-wrap"><table className="data-table orders-table"><thead><tr><th>Decided / scheduled</th><th>Portfolio</th><th>Stock</th><th>Side</th><th className="numeric">Qty</th><th className="numeric">Price</th><th className="numeric">Value / fees</th><th>Reason</th><th>Status</th></tr></thead><tbody>{pageRows.map((order) => {
        const portfolio = portfolios.find((item) => item.id === order.portfolio_id), currency = portfolio?.currency || "USD";
        return <tr key={order.id} className={`order-row ${order.isPending ? "pending-trade-row" : ""}`} role={onOrder ? "button" : undefined} tabIndex={onOrder ? 0 : undefined} onClick={() => onOrder?.(order)} onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && onOrder) { event.preventDefault(); onOrder(order); } }} aria-haspopup={onOrder ? "dialog" : undefined} aria-label={`${order.isPending ? "Open pending estimate for " : "Open details for "}${order.side} ${order.quantity} ${order.ticker_id}`}><td data-label="Decided / scheduled">{order.isPending ? <>Scheduled {dateTime(order.scheduled_for)}<small className="table-subline">Estimate</small></> : dateTime(order.created_at)}</td><td data-label="Portfolio">{portfolio?.name || "Paper portfolio"}</td><td data-label="Stock"><button className="ticker-link order-ticker" onClick={(event) => { event.stopPropagation(); onTicker(order.ticker_id); }}><TickerMark symbol={order.ticker_id} tickers={tickers}/>{order.ticker_id}</button></td><td data-label="Side"><span className={`side-badge ${order.side}`}>{order.side}</span></td><td className="numeric" data-label="Quantity">{order.isPending ? "~" : ""}{number(order.quantity, 0)}{order.isPending && <small className="table-subline">Estimated shares</small>}</td><td className="numeric" data-label="Price">{order.price > 0 ? `${order.isPending ? "~" : ""}${money(order.price, currency)}` : order.isPending && quoteLoading ? <Skeleton variant="inline" width="48px"/> : "—"}{order.isPending && <small className="table-subline">Estimated price</small>}</td><td className="numeric" data-label="Value / fees">{order.isPending && quoteLoading && !(order.gross_value > 0) ? <Skeleton variant="inline" width="52px"/> : order.isPending ? `~${money(order.gross_value, currency)}` : money(order.gross_value, currency)}<small className="table-subline">{order.isPending ? `Est. fees ${money(order.transaction_cost, currency)}` : `Fees ${money(order.transaction_cost, currency)}`}</small></td><td data-label="Reason">{formatReason(order.reason || "manual")}{order.isPending && <small className="table-subline">Pending rebalance</small>}{(order.event_id || order.event_ids?.length || order.plan?.event_ids?.length) && <small className="table-subline">News linked</small>}</td><td data-label="Status"><span className={`status-pill ${order.isPending ? "pending" : "filled"}`}>{order.isPending ? "Pending" : "Executed"}</span></td></tr>;
      })}</tbody></table></div><PagePagination page={page} totalPages={totalPages} hasMore={hasMoreOrders} onPage={changePage} loading={loadingMore}/></DataNotice>
    </section>
    {orderForm && <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setOrderForm(false); }}><form className="order-modal" onSubmit={submit}><div className="modal-header"><div><div className="eyebrow">PAPER EXECUTION</div><h2>New paper order</h2></div><button type="button" className="icon-button" onClick={() => setOrderForm(false)} aria-label="Close order form">×</button></div><div className="paper-alert">This order will be simulated in the selected portfolio. No live broker is connected.</div><label>Portfolio<select required value={selected?.id || ""} onChange={(e) => setPortfolioId(e.target.value)}>{portfolios.map((p) => <option key={p.id} value={p.id}>{p.name} · {money(p.portfolio_value, p.currency)}</option>)}</select></label><div className="form-two"><label>Ticker<input required value={form.ticker_id} onChange={(e) => { setForm({ ...form, ticker_id: e.target.value.toUpperCase() }); setQuote(null); }} placeholder="e.g. AAPL" maxLength={12}/></label><label>Side<select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}><option value="buy">Buy</option><option value="sell">Sell</option></select></label></div><div className="form-two"><label>Shares<input required type="number" min="1" step="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} placeholder="Number of shares"/></label><button type="button" className="button-secondary quote-button" onClick={priceLookup}>Get latest reference price</button></div>{quote && <div className="order-estimate"><span><small>REFERENCE PRICE</small><b>{money(quote.price, quote.currency)}</b><em className={changeClass(quote.change)}>{quote.change == null ? "Daily move unavailable" : `${quote.change > 0 ? "+" : ""}${quote.change.toFixed(2)}% today`}</em></span><span><small>ESTIMATED VALUE</small><b>{money(estimatedGross, quote.currency)}</b><em>{form.side === "buy" ? "Estimated cash outflow" : "Before fees"}</em></span><span><small>EST. TRANSACTION COST</small><b>{money(estimatedFee, quote.currency)}</b><em>{percent(currentPortfolio?.config?.transaction_cost || 0)} per side</em></span><span><small>AVAILABLE CASH</small><b>{money(currentPortfolio?.cash, currentPortfolio?.currency || "USD")}</b><em>{form.side === "buy" ? `Est. total ${money(estimatedGross + estimatedFee, quote.currency)}` : "Final cash is confirmed by service"}</em></span></div>}{quoteError && <p className="form-error">{quoteError}</p>}{message && <p className="form-error">{message}</p>}<div className="modal-actions"><button type="button" className="button-secondary" onClick={() => setOrderForm(false)}>Cancel</button><button className="button-primary" disabled={submitting || !portfolios.length}>{submitting ? "Submitting…" : `Place paper ${form.side} order`}</button></div></form></div>}
  </>;
}
