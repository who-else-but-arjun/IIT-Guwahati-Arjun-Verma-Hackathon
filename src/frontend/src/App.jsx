import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell, Drawer, SentimentMeter } from "./components/AppShell";
import { EventDrawer, OrderDetailDrawer, StockDrawer } from "./components/DetailsDrawers";
import { usePolling } from "./hooks/usePolling";
import { api, affectedTickers, analysisStatus, eventId, eventTime } from "./services/api";
import { NewsPage } from "./pages/NewsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { LedgerPage } from "./pages/LedgerPage";
import { OrdersPage } from "./pages/OrdersPage";
import { UniversePage } from "./pages/UniversePage";
import { changeClass, dateTime, money, number, percent, timeAgo } from "./utils/format";

const validPages = new Set(["news", "portfolio", "ledger", "orders", "universe"]);
const fullyAnalyzed = (event) => analysisStatus(event) === "complete" && Boolean(event.category) && event.sentiment?.impact_score != null;
function readRoute() {
  const pathPage = window.location.pathname.split("/").filter(Boolean)[0];
  const hashPage = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const page = pathPage && pathPage !== "index.html" ? pathPage : hashPage;
  return validPages.has(page) ? page : "news";
}

export default function App() {
  const [page, setPage] = useState(readRoute);
  const [routeTicker, setRouteTicker] = useState("");
  const [detail, setDetail] = useState(null);
  const eventsLoader = useCallback(async () => {
    return api.events({ limit: 100, offset: 0 });
  }, []);
  const portfolioLoader = useCallback(async () => (await api.portfolios()).portfolios || [], []);
  const healthLoader = useCallback(async () => {
    const [nlp, trading] = await Promise.allSettled([api.nlpHealth(), api.tradingHealth()]);
    return { nlp: nlp.status === "fulfilled" ? nlp.value : null, trading: trading.status === "fulfilled" ? trading.value : null, errors: [nlp, trading].filter((x) => x.status === "rejected").map((x) => x.reason.message) };
  }, []);
  const graphLoader = useCallback(async () => (await api.tickers()).tickers || [], []);
  const universeLoader = useCallback(async () => (await api.tickerUniverse()).tickers || [], []);
  const eventsState = usePolling(eventsLoader, 30_000, [eventsLoader], "latest-analyzed-news-v5");
  const listedState = usePolling(portfolioLoader, 90_000, [portfolioLoader], "portfolios");
  const healthState = usePolling(healthLoader, 30_000, [healthLoader]);
  const graphState = usePolling(graphLoader, 180_000, [graphLoader], "ticker-graph");
  const universeState = usePolling(universeLoader, 6 * 60 * 60 * 1000, [universeLoader], "ticker-universe");
  const portfolioIds = (listedState.data || []).map((portfolio) => portfolio.id).filter(Boolean);
  const portfolioKey = portfolioIds.join(",");
  const detailsLoader = useCallback(async () => {
    const results = await Promise.allSettled(portfolioIds.map((id) => api.portfolio(id)));
    const details = {};
    results.forEach((result, index) => { if (result.status === "fulfilled") details[portfolioIds[index]] = result.value; });
    return details;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolioKey]);
  const activityLoader = useCallback(async () => {
    const pairs = await Promise.all(portfolioIds.map(async (id) => {
      const [firstOrders, pending] = await Promise.allSettled([api.orders(id, 500, 0), api.pending(id)]);
      const orderCount = firstOrders.status === "fulfilled" ? Number(firstOrders.value.total_count) || 0 : 0;
      const orderPages = firstOrders.status === "fulfilled" ? await Promise.all(Array.from({ length: Math.ceil(Math.max(0, orderCount - 500) / 500) }, (_, page) => api.orders(id, 500, (page + 1) * 500).catch(() => ({ orders: [] })))) : [];
      const orders = firstOrders.status === "fulfilled" ? [...(firstOrders.value.orders || []), ...orderPages.flatMap((page) => page.orders || [])] : [];
      return [id, { orders, orderCount, hasMoreOrders: orders.length < orderCount, pending: pending.status === "fulfilled" ? pending.value.pending_rebalances || [] : [], rebalances: pending.status === "fulfilled" ? pending.value.rebalance_history || [] : [] }];
    }));
    return Object.fromEntries(pairs);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolioKey]);
  const detailsState = usePolling(detailsLoader, portfolioIds.length ? 60_000 : 0, [detailsLoader], `portfolio-details:${portfolioKey}`);
  const activityState = usePolling(activityLoader, portfolioIds.length ? 60_000 : 0, [activityLoader], `portfolio-activity:${portfolioKey}`);
  const portfolios = useMemo(() => (listedState.data || []).map((item) => detailsState.data?.[item.id] || item), [listedState.data, detailsState.data]);
  const ordersByPortfolio = activityState.data || {};
  const allOrders = useMemo(() => Object.values(ordersByPortfolio).flatMap((row) => row.orders || []), [ordersByPortfolio]);
  const hasMoreOrders = Object.values(ordersByPortfolio).some((row) => row.hasMoreOrders);
  const allPendingByPortfolio = useMemo(() => Object.fromEntries(Object.entries(ordersByPortfolio).map(([id, row]) => [id, row.pending || []])), [ordersByPortfolio]);
  const rebalanceHistoryByPortfolio = useMemo(() => Object.fromEntries(Object.entries(ordersByPortfolio).map(([id, row]) => [id, row.rebalances || []])), [ordersByPortfolio]);
  const pendingByPortfolio = useMemo(() => {
    const today = new Date().toLocaleDateString();
    return Object.fromEntries(Object.entries(ordersByPortfolio).map(([id, row]) => [id, (row.pending || []).filter((plan) => plan.scheduled_for && new Date(plan.scheduled_for).toLocaleDateString() === today)]));
  }, [ordersByPortfolio]);
  const newsFeedEvents = eventsState.data?.events || [];
  const events = newsFeedEvents.filter(fullyAnalyzed);
  const portfolioSymbols = portfolios.flatMap((portfolio) => (portfolio.positions || []).map((position) => position.ticker_id));
  // Keep the quote request stable across news-page refreshes. Rotating the
  // symbols with each new story caused a new Yahoo batch even for held assets.
  const quoteSymbols = [...new Set([
    ...(universeState.data || []).map((ticker) => ticker.ticker_id),
    ...portfolioSymbols,
  ])];
  const quoteKey = quoteSymbols.join(",");
  const [marketPrices, setMarketPrices] = useState({});
  const [quoteLoading, setQuoteLoading] = useState(true);
  const [quotesUpdatedAt, setQuotesUpdatedAt] = useState(null);
  useEffect(() => {
    if (!quoteSymbols.length) {
      if (universeState.data != null && listedState.data != null) setQuoteLoading(false);
      return undefined;
    }
    let cancelled = false;
    try {
      const snapshot = JSON.parse(window.sessionStorage.getItem(`crisil:quotes:${quoteKey}`) || "null");
      if (snapshot?.savedAt && Date.now() - snapshot.savedAt < 24 * 60 * 60 * 1000) {
        setMarketPrices((prior) => ({ ...prior, ...snapshot.data }));
        setQuoteLoading(false);
      }
    } catch { /* Stored quotes only provide a faster first paint. */ }
    const load = async () => {
      const batches = Array.from({ length: Math.ceil(quoteSymbols.length / 25) }, (_, index) => quoteSymbols.slice(index * 25, (index + 1) * 25));
      const responses = await Promise.all(batches.map((symbols) => api.quotes(symbols).catch(() => ({ quotes: [] }))));
      const entries = responses.flatMap((response) => response.quotes || []).map((quote) => {
        const bars = quote.ticker_data || [], current = bars.at(-1), previous = bars.at(-2);
        if (!current?.close) return null;
        return [quote.ticker, { price: current.close, change: previous?.close ? (current.close / previous.close - 1) * 100 : null, company: quote.company || quote.ticker, currency: "USD", timestamp: current.timestamp, sparkline: bars.slice(-63).map((item) => item.close).filter(Number.isFinite) }];
      }).filter(Boolean);
      if (cancelled) return;
      setQuoteLoading(false);
      const fresh = Object.fromEntries(entries);
      setMarketPrices((prior) => ({ ...prior, ...fresh }));
      try { window.sessionStorage.setItem(`crisil:quotes:${quoteKey}`, JSON.stringify({ savedAt: Date.now(), data: fresh })); } catch { /* Storage is optional. */ }
      setQuotesUpdatedAt(new Date());
    };
    load(); const timer = window.setInterval(load, 180_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteKey, universeState.data == null, listedState.data == null]);
  const health = healthState.data;
  const fullyConnected = health?.nlp?.status === "ok" && health?.trading?.status === "ok";
  const healthLabel = fullyConnected ? "ok" : health ? "degraded" : "";
  const shellQuotes = useMemo(() => {
    const positions = new Map();
    for (const portfolio of portfolios) for (const pos of portfolio.positions || []) {
      const prior = positions.get(pos.ticker_id);
      positions.set(pos.ticker_id, { ticker: pos.ticker_id, price: marketPrices[pos.ticker_id]?.price || pos.last_price, change: marketPrices[pos.ticker_id]?.change ?? null, company: pos.ticker_id, currency: portfolio.currency, sparkline: marketPrices[pos.ticker_id]?.sparkline, weight: Math.max(prior?.weight || 0, pos.weight || 0) });
    }
    for (const [ticker, quote] of Object.entries(marketPrices)) if (!positions.has(ticker)) positions.set(ticker, { ticker, price: quote.price, change: quote.change, company: quote.company, currency: quote.currency, sparkline: quote.sparkline });
    return [...positions.values()].sort((a, b) => (b.weight || 0) - (a.weight || 0));
  }, [portfolios, marketPrices]);
  const navigate = useCallback((destination, options = {}) => {
    const normalized = validPages.has(destination) ? destination : "news";
    setRouteTicker(options.ticker || "");
    setPage(normalized);
    if (window.location.pathname !== "/" + normalized) window.history.pushState({}, "", "/" + normalized);
    if (options.ticker && normalized === "universe") setDetail({ type: "none" });
  }, []);
  useEffect(() => {
    const update = () => { const nextPage = readRoute(); setPage(nextPage); if (nextPage !== "universe") setRouteTicker(""); setDetail(null); };
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    if (!validPages.has(window.location.pathname.split("/").filter(Boolean)[0]) && !validPages.has(window.location.hash.replace(/^#\/?/, ""))) window.history.replaceState({}, "", "/news");
    return () => { window.removeEventListener("popstate", update); window.removeEventListener("hashchange", update); };
  }, []);
  const openEvent = useCallback((event) => setDetail({ type: "event", event }), []);
  const openTicker = useCallback((ticker) => setDetail({ type: "stock", ticker }), []);
  const openOrder = useCallback((order) => setDetail({ type: "order", order }), []);
  const [loadingMoreEvents, setLoadingMoreEvents] = useState(false);
  const [loadingMoreOrders, setLoadingMoreOrders] = useState(false);
  const loadMoreEvents = useCallback(async () => {
    if (loadingMoreEvents) return;
    setLoadingMoreEvents(true);
    try {
      const rawPage = await api.events({ limit: 20, offset: newsFeedEvents.length });
      const pageResult = { ...rawPage, events: rawPage.events || [] };
      eventsState.setData((current) => {
        const rows = current?.events || [];
        const seen = new Set(rows.map(eventId));
        return { ...pageResult, events: [...rows, ...pageResult.events.filter((event) => !seen.has(eventId(event)))] };
      });
    } finally { setLoadingMoreEvents(false); }
  }, [newsFeedEvents.length, eventsState.setData, loadingMoreEvents]);
  const loadMoreOrders = useCallback(async () => {
    if (loadingMoreOrders) return;
    setLoadingMoreOrders(true);
    try {
      const pages = await Promise.all(portfolioIds.map(async (id) => {
        const current = ordersByPortfolio[id] || {};
        if (!current.hasMoreOrders) return [id, current];
        const result = await api.orders(id, 100, (current.orders || []).length);
        return [id, { ...current, orders: [...(current.orders || []), ...(result.orders || [])], orderCount: result.total_count || current.orderCount || 0, hasMoreOrders: Boolean(result.has_more) }];
      }));
      activityState.setData((current) => ({ ...current, ...Object.fromEntries(pages) }));
    } finally { setLoadingMoreOrders(false); }
  }, [activityState.setData, loadingMoreOrders, ordersByPortfolio, portfolioIds]);
  const refreshAll = useCallback(async () => Promise.all([eventsState.refresh(), listedState.refresh(), detailsState.refresh(), activityState.refresh()]), [eventsState.refresh, listedState.refresh, detailsState.refresh, activityState.refresh]);
  const placeRebalance = useCallback(async (id) => { const result = await api.rebalance(id); await refreshAll(); return result; }, [refreshAll]);
  const eventStateError = eventsState.error;
  const priceQuotes = useMemo(() => Object.fromEntries(Object.entries(marketPrices)), [marketPrices]);
  const quoteHeaderUpdated = quotesUpdatedAt || detailsState.updatedAt;
  const drawer = detail?.type === "event" ? <EventDrawer key={eventId(detail.event) || detail.event.headline} event={detail.event} portfolios={portfolios} orders={allOrders} pending={allPendingByPortfolio} prices={marketPrices} onClose={() => setDetail(null)} onTicker={openTicker}/> : detail?.type === "stock" ? <StockDrawer key={detail.ticker} symbol={detail.ticker} portfolios={portfolios} orders={allOrders} tickers={graphState.data || []} onClose={() => setDetail(null)} hasMoreOrders={hasMoreOrders} onLoadMoreOrders={loadMoreOrders} loadingMoreOrders={loadingMoreOrders} onEvent={openEvent}/> : detail?.type === "order" ? <OrderDetailDrawer key={detail.order.id} order={detail.order} portfolios={portfolios} events={events} tickers={graphState.data || []} onClose={() => setDetail(null)} onEvent={openEvent} onTicker={openTicker}/> : null;
  const pageContent = page === "news" ? <NewsPage events={newsFeedEvents} totalEvents={eventsState.data?.total_count} loading={eventsState.loading} quoteLoading={quoteLoading} error={eventStateError} refresh={eventsState.refresh} updatedAt={eventsState.updatedAt} quotes={shellQuotes} prices={priceQuotes} tickers={graphState.data || []} trackedStockCount={universeState.data?.length || 0} onEvent={openEvent} onTicker={openTicker} hasMore={eventsState.data?.has_more} onLoadMore={loadMoreEvents} loadingMore={loadingMoreEvents}/> : page === "portfolio" ? <PortfolioPage portfolios={portfolios} portfolioOrders={allOrders} loading={listedState.loading || detailsState.loading} quoteLoading={quoteLoading} error={listedState.error || (detailsState.error && !Object.keys(detailsState.data || {}).length ? detailsState.error : "")} refresh={refreshAll} onTicker={openTicker} onOrders={() => navigate("orders")} onRebalance={placeRebalance} pending={pendingByPortfolio} rebalances={rebalanceHistoryByPortfolio} prices={marketPrices} events={events} onEvent={openEvent} tickers={graphState.data || []}/> : page === "ledger" ? <LedgerPage events={events} loading={eventsState.loading || activityState.loading} error={eventsState.error || ""} refresh={eventsState.refresh} portfolios={portfolios} orders={allOrders} pending={allPendingByPortfolio} rebalances={rebalanceHistoryByPortfolio} onEvent={openEvent} onTicker={openTicker} hasMore={eventsState.data?.has_more} onLoadMore={loadMoreEvents} loadingMore={loadingMoreEvents} hasMoreOrders={hasMoreOrders} onLoadMoreOrders={loadMoreOrders} loadingMoreOrders={loadingMoreOrders}/> : page === "orders" ? <OrdersPage portfolios={portfolios} data={ordersByPortfolio} tickers={graphState.data || []} pending={allPendingByPortfolio} prices={marketPrices} quoteLoading={quoteLoading} loading={activityState.loading} error={activityState.error || ""} refresh={activityState.refresh} initialTicker={routeTicker} onTicker={openTicker} onOrder={openOrder} onLoadMore={loadMoreOrders} loadingMore={loadingMoreOrders}/> : <UniversePage tickers={graphState.data || []} loading={graphState.loading} error={graphState.error || ""} refresh={graphState.refresh} events={events} portfolios={portfolios} onTicker={openTicker} focusTicker={routeTicker}/>;
  return <AppShell page={page} onNavigate={navigate} health={healthLabel} quotes={shellQuotes} quoteLoading={quoteLoading} events={events} onEvent={openEvent} onTicker={openTicker} updatedAt={quoteHeaderUpdated}>{pageContent}{drawer}</AppShell>;
}

