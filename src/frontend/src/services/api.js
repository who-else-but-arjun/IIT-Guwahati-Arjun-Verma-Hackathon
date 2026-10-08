const NLP_API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TRADING_API = (import.meta.env.VITE_TRADING_API_URL || "http://localhost:8001").replace(/\/$/, "");

async function request(url, options = {}) {
  let response;
  try {
    const headers = { ...options.headers };
    // GET requests do not need a content type. Keeping the header off them
    // avoids unnecessary CORS preflights, which can leave ledger activity
    // looking as though it is still loading when the API itself is healthy.
    if (options.body != null && !Object.keys(headers).some((key) => key.toLowerCase() === "content-type")) {
      headers["Content-Type"] = "application/json";
    }
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new Error(`Cannot reach ${url.includes(":8001") ? "the paper-trading service" : "the news service"}. Check that the backend is running.`);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

export const api = {
  nlpHealth: () => request(`${NLP_API}/api/health/`),
  tradingHealth: () => request(`${TRADING_API}/api/trading/health/`),
  events: (params = {}) => request(`${NLP_API}/api/events/?${new URLSearchParams({ limit: 50, offset: 0, ...params })}`),
  event: (id) => request(`${NLP_API}/api/events/${encodeURIComponent(id)}/`),
  ticker: (symbol, period = "3mo", interval = "1d") => request(`${NLP_API}/api/tickers/${encodeURIComponent(symbol)}/?period=${period}&interval=${interval}`),
  tickers: () => request(`${NLP_API}/api/tickers/`),
  tickerUniverse: () => request(`${NLP_API}/api/tickers/universe/`),
  quotes: (symbols) => request(`${NLP_API}/api/tickers/quotes/?symbols=${encodeURIComponent(symbols.join(","))}`),
  tickerEvents: (symbol, params = {}) => request(`${NLP_API}/api/tickers/${encodeURIComponent(symbol)}/events/?${new URLSearchParams({ limit: 50, offset: 0, ...params })}`),
  portfolios: () => request(`${TRADING_API}/api/trading/portfolios/`),
  portfolio: (id) => request(`${TRADING_API}/api/trading/portfolios/${encodeURIComponent(id)}/`),
  orders: (id, limit = 100, offset = 0, tickerId = "") => request(`${TRADING_API}/api/trading/portfolios/${encodeURIComponent(id)}/orders/?${new URLSearchParams({ limit, offset, ...(tickerId ? { ticker_id: tickerId } : {}) })}`),
  pending: (id) => request(`${TRADING_API}/api/trading/portfolios/${encodeURIComponent(id)}/orders/pending/`),
  eventActivity: (eventIds) => request(`${TRADING_API}/api/trading/events/activity/?${new URLSearchParams(eventIds.map((id) => ["event_id", id]))}`),
  placeOrder: (id, body) => request(`${TRADING_API}/api/trading/portfolios/${encodeURIComponent(id)}/orders/`, { method: "POST", body: JSON.stringify(body) }),
  rebalance: (id) => request(`${TRADING_API}/api/trading/portfolios/${encodeURIComponent(id)}/rebalance/`, { method: "POST", body: JSON.stringify({ force: true }) }),
};

export const eventId = (event) => event?.event_id || event?.id || event?._id || "";
export const eventTime = (event) => {
  if (event?.event_timestamp) return event.event_timestamp;
  if (!event?.date) return null;
  const time = String(event.time || "00:00:00");
  return `${event.date}T${time}${/[zZ]|[+-]\d\d:?\d\d$/.test(time) ? "" : "Z"}`;
};
export const affectedTickers = (event) => (event?.relevant_tickers || []).map((item) => typeof item === "string" ? { ticker_id: item, relevance_score: 0 } : item).sort((a, b) => (Number(b.relevance_score) || 0) - (Number(a.relevance_score) || 0));
export const analysisStatus = (event) => event?.metadata?.analysis_status || (event?.sentiment ? "complete" : "pending_analysis");
