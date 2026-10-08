import { useEffect, useMemo, useState } from "react";
import { analysisStatus, api, affectedTickers, eventId, eventTime } from "../services/api";
import { DataNotice, NewsCategoryIcon, PageHeading, PagePagination, SentimentMeter } from "../components/AppShell";
import { cleanText, dateTime, formatReason, impactScore, money, timeAgo } from "../utils/format";
import { RebalanceDetailDrawer } from "../components/RebalanceDrawer";

const PAGE_SIZE = 10;
const isAnalyzed = (event) => analysisStatus(event) === "complete" && event.category &&
  event.sentiment?.score != null && event.sentiment?.impact_score != null;
const planEventIds = (plan) => new Set([...(plan?.event_ids || []), ...Object.values(plan?.ticker_event_ids || {}).flat()]);

export function LedgerPage({ events = [], loading, error, refresh, portfolios = [], orders = [], pending = {}, rebalances = {}, tickers = [], onEvent, onTicker, hasMore, onLoadMore, loadingMore, hasMoreOrders, onLoadMoreOrders, loadingMoreOrders }) {
  const [view, setView] = useState("news");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [queuedPage, setQueuedPage] = useState(null);
  const [rebalancePage, setRebalancePage] = useState(1);
  const [queuedRebalancePage, setQueuedRebalancePage] = useState(null);
  const [activeRebalance, setActiveRebalance] = useState(null);
  const [resolvedActivity, setResolvedActivity] = useState({ orders: [], rebalances: [] });
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState("");
  const eventIdsKey = useMemo(() => [...new Set(events.map(eventId).filter(Boolean))].sort().join(","), [events]);
  useEffect(() => {
    const ids = eventIdsKey ? eventIdsKey.split(",") : [];
    if (!ids.length) { setResolvedActivity({ orders: [], rebalances: [] }); return undefined; }
    let current = true;
    setActivityLoading(true);
    setActivityError("");
    Promise.all(ids.reduce((batches, id, index) => {
      if (index % 50 === 0) batches.push([]);
      batches.at(-1).push(id);
      return batches;
    }, []).map((batch) => api.eventActivity(batch))).then((results) => {
      if (current) setResolvedActivity({
        orders: [...new Map(results.flatMap((result) => result.orders || []).map((order) => [order.id, order])).values()],
        rebalances: [...new Map(results.flatMap((result) => result.rebalances || []).map((plan) => [plan.id, plan])).values()],
      });
    }).catch(() => {
      if (current) { setResolvedActivity({ orders: [], rebalances: [] }); setActivityError("Could not load linked portfolio activity. Retry the ledger to verify event links."); }
    }).finally(() => { if (current) setActivityLoading(false); });
    return () => { current = false; };
  }, [eventIdsKey]);
  const ledgerOrders = useMemo(() => [...new Map([...(orders || []), ...resolvedActivity.orders].map((order) => [order.id, order])).values()], [orders, resolvedActivity.orders]);
  const ledgerPlans = useMemo(() => [...new Map([...Object.entries(pending || {}).flatMap(([portfolioId, plans]) => (plans || []).map((plan) => ({ ...plan, portfolio_id: plan.portfolio_id || portfolioId }))), ...Object.entries(rebalances || {}).flatMap(([portfolioId, plans]) => (plans || []).map((plan) => ({ ...plan, portfolio_id: plan.portfolio_id || portfolioId }))), ...resolvedActivity.rebalances].map((plan) => [plan.id, plan])).values()], [pending, rebalances, resolvedActivity.rebalances]);
  const portfolioName = (id) => portfolios.find((item) => item.id === id)?.name || "Paper portfolio";
  const eventRows = useMemo(() => events.filter(isAnalyzed).filter((event) => {
    const id = eventId(event), eventOrders = ledgerOrders.filter((order) => order.event_id === id || (order.event_ids || []).includes(id));
    const eventPlans = ledgerPlans.filter((plan) => planEventIds(plan).has(id));
    const action = eventOrders.length || eventPlans.some((plan) => plan.status === "filled") ? "ordered" : eventPlans.some((plan) => plan.status === "pending") ? "pending" : eventPlans.some((plan) => plan.status === "cancelled" && /merged into plan/i.test(plan.last_error || "")) ? "consolidated" : "no_action";
    const tickerNames = affectedTickers(event).map((item) => item.ticker_id).join(" ");
    return (!query || `${cleanText(event.headline)} ${tickerNames}`.toLowerCase().includes(query.toLowerCase())) && (!status || action === status);
  }), [events, ledgerOrders, ledgerPlans, query, status]);
  const rebalanceRows = useMemo(() => {
    const grouped = new Map();
    for (const order of orders) {
      if (!order.reason || order.reason === "manual") continue;
      const executedAt = order.executed_at || order.created_at;
      const batch = String(executedAt || "").slice(0, 16);
      const key = [order.portfolio_id, batch, order.reason].join("|");
      const row = grouped.get(key) || { key, portfolio_id: order.portfolio_id, created_at: order.created_at, reason: order.reason, orders: [], tickers: new Set(), eventIds: new Set(), gross: 0, fees: 0 };
      row.orders.push(order); row.tickers.add(order.ticker_id); row.gross += Number(order.gross_value) || 0; row.fees += Number(order.transaction_cost) || 0;
      for (const id of [...(order.event_ids || []), ...(order.event_id ? [order.event_id] : [])]) row.eventIds.add(id);
      if (new Date(executedAt) > new Date(row.created_at)) row.created_at = executedAt;
      grouped.set(key, row);
    }
    const past = [...grouped.values()].map((row) => ({ ...row, pending: false, tickers: [...row.tickers], eventIds: [...row.eventIds] }));
    const plans = [...new Map([...ledgerPlans, ...Object.entries(rebalances || {}).flatMap(([portfolioId, rows]) => (rows || []).map((plan) => ({ ...plan, portfolio_id: plan.portfolio_id || portfolioId })))].map((plan) => [plan.id, plan])).values()];
    const planRows = [];
    for (const plan of plans) {
      if (!["pending", "filled"].includes(plan.status)) continue;
      const eventIds = [...planEventIds(plan)];
      const stamp = plan.executed_at || plan.scheduled_for || plan.decision_at;
      const linkedOrderRow = plan.status === "filled" ? past.find((row) => row.portfolio_id === plan.portfolio_id
        && row.reason === plan.reason
        && (Math.abs(new Date(row.created_at) - new Date(stamp)) < 5 * 60_000
          || row.eventIds.some((id) => eventIds.includes(id)))) : null;
      if (linkedOrderRow) {
        linkedOrderRow.eventIds = [...new Set([...linkedOrderRow.eventIds, ...eventIds])];
        linkedOrderRow.plan = plan;
        continue;
      }
      planRows.push({
        key: `plan-${plan.id}`, portfolio_id: plan.portfolio_id, created_at: stamp,
        scheduled_for: plan.scheduled_for, reason: plan.reason,
        targetCount: Object.values(plan.target_weights || {}).filter((weight) => Number(weight) > 0).length,
        eventIds, pending: plan.status === "pending", planOnly: true, plan,
        orders: [], tickers: [], gross: 0, fees: 0,
      });
    }
    return [...planRows, ...past].filter((row) => !query || `${portfolioName(row.portfolio_id)} ${row.reason} ${row.tickers.join(" ")} ${row.eventIds.join(" ")}`.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => new Date(b.pending ? b.created_at : b.created_at) - new Date(a.pending ? a.created_at : a.created_at));
  }, [orders, pending, rebalances, ledgerPlans, portfolios, query]);
  const totalPages = Math.max(1, Math.ceil(eventRows.length / PAGE_SIZE));
  const pageRows = eventRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const rebalanceTotalPages = Math.max(1, Math.ceil(rebalanceRows.length / PAGE_SIZE));
  const rebalancePageRows = rebalanceRows.slice((rebalancePage - 1) * PAGE_SIZE, rebalancePage * PAGE_SIZE);
  useEffect(() => {
    if (queuedPage != null && queuedPage <= totalPages) { setPage(queuedPage); setQueuedPage(null); }
    else if (queuedPage != null && !hasMore) { setPage(totalPages); setQueuedPage(null); }
    else setPage((current) => Math.min(current, totalPages));
  }, [queuedPage, totalPages, hasMore]);
  useEffect(() => {
    if (queuedRebalancePage != null && queuedRebalancePage <= rebalanceTotalPages) { setRebalancePage(queuedRebalancePage); setQueuedRebalancePage(null); }
    else if (queuedRebalancePage != null && !hasMoreOrders) { setRebalancePage(rebalanceTotalPages); setQueuedRebalancePage(null); }
    else setRebalancePage((current) => Math.min(current, rebalanceTotalPages));
  }, [queuedRebalancePage, rebalanceTotalPages, hasMoreOrders]);
  const changePage = (next) => {
    if (next <= totalPages) { setPage(next); setQueuedPage(null); return; }
    if (hasMore) { setQueuedPage(next); if (!loadingMore) onLoadMore?.(); }
  };
  const changeRebalancePage = (next) => {
    if (next <= rebalanceTotalPages) { setRebalancePage(next); setQueuedRebalancePage(null); return; }
    if (hasMoreOrders) { setQueuedRebalancePage(next); if (!loadingMoreOrders) onLoadMoreOrders?.(); }
  };

  return <>
    <PageHeading kicker="AUDIT TRAIL" title="Event Ledger" description="Review completed news analysis and trace strategy decisions through scheduled and executed rebalances." actions={<span className="paper-pill">PAPER PORTFOLIO AUDIT</span>} />
    <div className="ledger-tabs" role="tablist" aria-label="Ledger view"><button role="tab" aria-selected={view === "news"} className={view === "news" ? "active" : ""} onClick={() => { setView("news"); setPage(1); setQueuedPage(null); }}>Analyzed news <span>{eventRows.length}</span></button><button role="tab" aria-selected={view === "rebalances"} className={view === "rebalances" ? "active" : ""} onClick={() => { setView("rebalances"); setRebalancePage(1); setQueuedRebalancePage(null); }}>Rebalancing history <span>{rebalanceRows.length}</span></button></div>
    <section className="filter-bar ledger-filters"><label className="filter-search"><span>⌕</span><input value={query} onChange={(e) => { setQuery(e.target.value); setPage(1); setQueuedPage(null); setRebalancePage(1); setQueuedRebalancePage(null); }} placeholder={view === "news" ? "Search analyzed headline or ticker" : "Search portfolio, strategy, ticker or event"}/></label>{view === "news" && <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); setQueuedPage(null); }} aria-label="Filter event actions"><option value="">All actions</option><option value="ordered">Order linked</option><option value="pending">Rebalance pending</option><option value="consolidated">Merged into rebalance</option><option value="no_action">No portfolio action</option></select>}<button className="icon-button refresh-button" onClick={refresh} aria-label="Refresh ledger">↻</button></section>
    {view === "news" ? <DataNotice skeleton="table" loading={loading && !eventRows.length} error={error} onRetry={refresh} empty={!pageRows.length && !hasMore ? "No analyzed news events match these filters." : null}>
      <div className="table-scroll ledger-table-wrap"><table className="data-table ledger-table"><thead><tr><th>Event</th><th>Affected stocks</th><th>Model signal</th><th>Portfolio activity</th><th>Feed time</th></tr></thead><tbody>{pageRows.map((event) => {
        const id = eventId(event), linkedOrders = ledgerOrders.filter((order) => order.event_id === id || (order.event_ids || []).includes(id));
        const linkedPlans = ledgerPlans.filter((plan) => planEventIds(plan).has(id)).map((plan) => ({ ...plan, portfolioId: plan.portfolio_id }));
        const pendingPlans = [...new Map(linkedPlans.filter((plan) => plan.status === "pending").map((plan) => [`${plan.portfolioId}|${plan.scheduled_for}`, plan])).values()];
        const filledPlans = [...new Map(linkedPlans.filter((plan) => plan.status === "filled").map((plan) => [`${plan.portfolioId}|${plan.executed_at || plan.scheduled_for}`, plan])).values()];
        const mergedPlans = linkedPlans.filter((plan) => plan.status === "cancelled" && /merged into plan/i.test(plan.last_error || ""));
        return <tr key={id || event.headline} onClick={() => onEvent(event)} tabIndex="0" onKeyDown={(e) => e.key === "Enter" && onEvent(event)}><td className="ledger-event"><span className="ledger-time">{dateTime(eventTime(event))}</span><b>{cleanText(event.headline)}</b><small>{event.category.replaceAll("_", " ")} · {event.metadata?.source || event.metadata?.provider || "News wire"}</small></td><td><div className="ledger-tickers">{affectedTickers(event).slice(0, 4).map((item) => <button key={item.ticker_id} onClick={(e) => { e.stopPropagation(); onTicker(item.ticker_id); }}>{item.ticker_id}</button>)}{!affectedTickers(event).length && <span className="muted">No ticker match</span>}</div></td><td><SentimentMeter score={event.sentiment.score}/><small className="table-subline">Impact {impactScore(event.sentiment.impact_score)} · analyzed</small></td><td>{linkedOrders.length ? <div className="activity-summary"><b>Executed rebalance · {linkedOrders.length} order{linkedOrders.length > 1 ? "s" : ""}</b><small>{linkedOrders.slice(0, 2).map((order) => `${order.side.toUpperCase()} ${order.quantity} ${order.ticker_id} · ${money(order.gross_value, "USD")}`).join(" / ")}</small></div> : pendingPlans.length ? <div className="activity-summary pending"><b>Rebalance pending</b><small>{pendingPlans.map((plan) => `${portfolioName(plan.portfolioId)} · ${dateTime(plan.scheduled_for)}`).join(" / ")}</small></div> : filledPlans.length ? <div className="activity-summary"><b>Rebalance executed</b><small>{filledPlans.map((plan) => `${portfolioName(plan.portfolioId)} · ${dateTime(plan.executed_at || plan.scheduled_for)}`).join(" / ")} · no paper orders recorded</small></div> : mergedPlans.length ? <div className="activity-summary pending"><b>Decision merged into rebalance</b><small>{mergedPlans.map((plan) => plan.last_error.replace(/^.*merged into plan\s+/i, "Consolidated plan ")).join(" / ")}</small></div> : activityLoading ? <span className="muted">Checking linked activity…</span> : activityError ? <span className="muted">{activityError}</span> : <span className="muted">No linked rebalance or trade</span>}</td><td className="muted">{timeAgo(eventTime(event))}</td></tr>;
      })}</tbody></table></div><PagePagination page={page} totalPages={totalPages} hasMore={hasMore} onPage={changePage} loading={loadingMore}/>
    </DataNotice> : <DataNotice skeleton="table" loading={loading && !rebalanceRows.length} error={error} onRetry={refresh} empty={!rebalanceRows.length && !hasMoreOrders ? "No pending or executed strategy rebalances are recorded." : null}>
      <div className="table-scroll ledger-table-wrap"><table className="data-table rebalance-ledger-table"><thead><tr><th>Decision / execution</th><th>Portfolio</th><th>Strategy</th><th>Positions</th><th>Linked news</th><th>Trading</th><th>Status</th></tr></thead><tbody>{rebalancePageRows.map((row) => <tr key={row.key} className="clickable-row" tabIndex="0" role="button" onClick={() => setActiveRebalance(row)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActiveRebalance(row); } }}><td><b>{dateTime(row.created_at)}</b>{row.pending && <small className="table-subline">Scheduled {dateTime(row.scheduled_for)}</small>}</td><td>{portfolioName(row.portfolio_id)}</td><td>{formatReason(row.reason)}</td><td>{row.pending || row.planOnly ? `${row.targetCount} target positions` : `${row.tickers.length} tickers · ${row.orders.length} orders`}</td><td>{row.eventIds.length ? <span title={row.eventIds.join(", ")}>{row.eventIds.length} event{row.eventIds.length === 1 ? "" : "s"}</span> : "—"}</td><td>{row.pending || row.planOnly ? "—" : <><b>{money(row.gross, portfolios.find((p) => p.id === row.portfolio_id)?.currency || "USD")}</b><small className="table-subline">Fees {money(row.fees, portfolios.find((p) => p.id === row.portfolio_id)?.currency || "USD")}</small></>}</td><td><span className={`status-pill ${row.pending ? "pending" : "filled"}`}>{row.pending ? "Pending" : row.planOnly ? "Executed · no orders" : "Executed"}</span></td></tr>)}</tbody></table></div><PagePagination page={rebalancePage} totalPages={rebalanceTotalPages} hasMore={hasMoreOrders} onPage={changeRebalancePage} loading={loadingMoreOrders}/>
    </DataNotice>}
    {activeRebalance && <RebalanceDetailDrawer row={activeRebalance} portfolios={portfolios} events={events} tickers={tickers} onClose={() => setActiveRebalance(null)} onEvent={(event) => { setActiveRebalance(null); onEvent(event); }} onTicker={(ticker) => { setActiveRebalance(null); onTicker(ticker); }}/>}
  </>;
}
