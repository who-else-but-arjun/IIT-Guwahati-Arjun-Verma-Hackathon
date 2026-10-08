import { useEffect, useRef, useState } from "react";
import { cleanText, timeAgo } from "../utils/format";
import { affectedTickers, eventId, eventTime } from "../services/api";

const routes = [["news", "News", "news"], ["portfolio", "Portfolio", "portfolio"], ["ledger", "Event Ledger", "ledger"], ["orders", "Orders", "orders"], ["universe", "Stock Universe", "universe"]];
const navPaths = {
  news: <><path d="M4 5h16v12H4z"/><path d="M4 9h16M8 17l-3 3m11-3 3 3"/><path d="M7 12h.01M10 12h.01M13 12h.01"/></>,
  portfolio: <><path d="M4 19V5m0 14h16M8 16v-4m4 4V8m4 8v-6m4 6V4"/></>,
  ledger: <><path d="M5 5h14M5 10h14M5 15h14M5 20h14"/><path d="M2 5h.01M2 10h.01M2 15h.01M2 20h.01"/></>,
  orders: <><path d="M5 7h14m-4-4 4 4-4 4M19 17H5m4-4-4 4 4 4"/></>,
  universe: <><circle cx="12" cy="12" r="2"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="m10.5 10.5-4-4m7 4 4-4m-7 7-4 4m7-4 4 4"/></>,
};
const sparkPath = (values = []) => {
  if (values.length < 2) return "";
  const min = Math.min(...values), span = Math.max(...values) - min || 1;
  return values.map((value, index) => `${index ? "L" : "M"}${(index * 64 / (values.length - 1)).toFixed(1)},${(21 - (value - min) * 18 / span).toFixed(1)}`).join(" ");
};

export function AppShell({ page, onNavigate, health, quotes = [], quoteLoading = false, events = [], onEvent, onTicker, children, updatedAt }) {
  const [query, setQuery] = useState("");
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem("crisil-theme") === "dark" ? "dark" : "light"; } catch { return "light"; } });
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [alert, setAlert] = useState(null);
  const audioRef = useRef(null), previousIds = useRef(null), toastTimer = useRef(null);
  const headlineEvents = events.slice(0, 20);
  useEffect(() => {
    const ids = events.map(eventId).filter(Boolean);
    if (previousIds.current === null) { previousIds.current = new Set(ids); return; }
    const previous = previousIds.current;
    const latest = events.find((event) => eventId(event) && !previous.has(eventId(event)));
    previousIds.current = new Set(ids);
    if (!latest) return;
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    setAlert(latest);
    toastTimer.current = window.setTimeout(() => setAlert(null), 8000);
    if (soundEnabled) {
      try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        const context = audioRef.current || new AudioContextClass(); audioRef.current = context;
        if (context.state === "suspended") context.resume();
        const oscillator = context.createOscillator(), gain = context.createGain();
        oscillator.type = "sine"; oscillator.frequency.value = 880;
        gain.gain.setValueAtTime(0.0001, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.11, context.currentTime + 0.025);
        gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.28);
        oscillator.connect(gain); gain.connect(context.destination); oscillator.start(); oscillator.stop(context.currentTime + 0.3);
      } catch { /* Browser audio can be unavailable or blocked. */ }
    }
  }, [events, soundEnabled]);
  useEffect(() => () => { if (toastTimer.current) window.clearTimeout(toastTimer.current); }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("crisil-theme", theme); } catch { /* Storage may be disabled. */ }
  }, [theme]);
  const search = (event) => {
    event.preventDefault();
    const value = query.trim().toUpperCase();
    if (value) { onTicker(value); setQuery(""); }
  };
  return <>
    <div className="run" aria-label="Latest financial news"><b>LIVE · LATEST</b><div className="rw"><div className="rt" style={{ "--d": `${Math.max(40, headlineEvents.length * 10)}s` }}>{headlineEvents.length ? [...headlineEvents, ...headlineEvents].map((event, index) => <button key={`${eventId(event)}-${index}`} onClick={() => onEvent(event)}><span className="tm">{timeAgo(eventTime(event))}</span><b className="rh">{cleanText(event.headline) || "Headline unavailable"}</b>{affectedTickers(event).slice(0, 2).map((ticker) => { const quote = quotes.find((item) => String(item.ticker).toUpperCase() === String(ticker.ticker_id).toUpperCase()); return <span className="runner-stock" key={ticker.ticker_id}>{ticker.ticker_id}<em className={quote?.change > 0 ? "up" : quote?.change < 0 ? "dn" : ""}>{quote?.change == null ? "—" : `${quote.change > 0 ? "+" : ""}${quote.change.toFixed(2)}%`}</em></span>; })}</button>) : <span className="tm">Waiting for headlines from the news service</span>}</div></div></div>
    <header className="top">
      <a className="brand" href="/news" aria-label="CRISIL home" onClick={(event) => { event.preventDefault(); onNavigate("news"); }}><span className="brand-wordmark">CRIS<span className="brand-i">ı</span>L</span></a>
      <nav aria-label="Primary">{routes.map(([id, label]) => <a key={id} href={"/" + id} className={page === id ? "on" : ""} onClick={(event) => { event.preventDefault(); onNavigate(id); }}><svg className="nav-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{navPaths[id]}</svg><span>{label}</span></a>)}</nav>
      <form className="global-lookup" onSubmit={search}><input list="ticker-suggestions" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search ticker" aria-label="Search ticker"/><datalist id="ticker-suggestions">{quotes.map((quote) => <option key={quote.ticker} value={quote.ticker}/>)}</datalist></form>
      <button className={`theme-toggle ${theme === "dark" ? "enabled" : ""}`} onClick={() => setTheme((value) => value === "light" ? "dark" : "light")} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`} aria-pressed={theme === "dark"} title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.7"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><i className="control-track"><b/></i></button>
      <button className={`sound-toggle ${soundEnabled ? "enabled" : ""}`} onClick={() => { if (!soundEnabled) { try { const AudioContextClass = window.AudioContext || window.webkitAudioContext; audioRef.current = audioRef.current || new AudioContextClass(); audioRef.current.resume(); } catch { /* Audio is optional. */ } } setSoundEnabled((value) => !value); }} aria-pressed={soundEnabled} aria-label={soundEnabled ? "Mute new story alerts" : "Enable sound for new story alerts"} title={soundEnabled ? "Mute new story alerts" : "Enable sound for new story alerts"}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10v4h4l5 4V6l-5 4H4Z"/>{soundEnabled ? <><path d="M16 9a4 4 0 0 1 0 6m2-8a7 7 0 0 1 0 10"/></> : <path d="m17 9 5 6m0-6-5 6"/>}</svg><i className="control-track"><b/></i></button>
      <span className={`connection-pill ${health === "ok" ? "connected" : ""}`} title={health === "ok" ? "News and portfolio services connected" : "One or more services are unavailable"}><i/>{health === "ok" ? "LIVE DATA" : "DATA STATUS"}</span>
    </header>
      <div className="pulse" aria-label="Market pulse"><div className="pt">{quotes.length ? [...quotes, ...quotes].map((quote, index) => <button className="pi" key={`${quote.ticker}-${index}`} onClick={() => onTicker(quote.ticker)}><b>{quote.ticker}</b><strong>{Number.isFinite(Number(quote.price)) ? Number(quote.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}</strong><em className={quote.change > 0 ? "up" : quote.change < 0 ? "dn" : ""}>{quote.change == null ? "—" : `${quote.change > 0 ? "+" : ""}${quote.change.toFixed(2)}%`}</em>{quote.sparkline?.length > 1 && <svg className={`sk ${quote.change < 0 ? "dn" : "up"}`} viewBox="0 0 64 24" aria-label={`${quote.ticker} recent price trend`}><path d={sparkPath(quote.sparkline)}/></svg>}<span className="market-source">{quote.company || "Market data"}</span></button>) : quoteLoading ? <Skeleton variant="market" count={7} className="pulse-skeleton"/> : <span className="pi">Waiting for live market data from the configured source</span>}</div></div>
    <div className="stat"><span><i className={`dot ${health === "ok" ? "up" : ""}`}/><b>{health === "ok" ? "Connected" : "Service status"}</b> · news and portfolio services</span><span><b>{updatedAt ? `Prices updated ${timeAgo(updatedAt)}` : "Market prices"}</b></span><span className="paper-context">Paper trading environment</span></div>
    <main id="app" className="page-main">{children}</main>
    {alert && <button className="news-toast" onClick={() => { onEvent(alert); setAlert(null); }} aria-live="polite"><span className="toast-live"><i/>NEW STORY</span><b>{cleanText(alert.headline) || "New market story"}</b><small>{affectedTickers(alert).slice(0, 3).map((ticker) => ticker.ticker_id).join(" · ") || "Open news brief"} · Click to view</small><span className="toast-close" onClick={(event) => { event.stopPropagation(); setAlert(null); }}>×</span></button>}
    <footer className="app-footer"><span>CRISIL FINANCIAL NLP</span><span>News, portfolios and paper execution</span><span>Market data updates when available</span></footer>
  </>;
}

export function PageHeading({ kicker, title, description, actions }) { return <><div className="eyebrow">{kicker}</div><div className="page-title-row"><h1>{title}</h1>{actions && <div className="heading-actions">{actions}</div>}</div>{description && <p className="sub">{description}</p>}</>; }

export function TickerMark({ symbol, tickers = [] }) {
  const normalizedSymbol = String(symbol || "").trim().toUpperCase();
  const record = tickers.find((ticker) => String(ticker.ticker_name?.ticker_id || ticker.ticker_id || "").trim().toUpperCase() === normalizedSymbol);
  const logoUrl = typeof record?.logo_url === "string" ? record.logo_url.trim() : "";
  return <span className="ticker-mark" aria-label={`${symbol} company mark`}>{logoUrl ? <img src={logoUrl} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true; event.currentTarget.parentElement.classList.add("logo-failed"); }}/> : null}<span className={logoUrl ? "ticker-mark-fallback" : ""}>{normalizedSymbol.slice(0, 2)}</span></span>;
}

const categoryIconPaths = {
  macro: <><circle cx="12" cy="12" r="8.5"/><path d="M3.8 12h16.4M12 3.5c2.2 2.3 3.2 5.1 3.2 8.5s-1 6.2-3.2 8.5c-2.2-2.3-3.2-5.1-3.2-8.5s1-6.2 3.2-8.5Z"/></>,
  earnings: <><path d="M6 3.5h8l4 4V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/><path d="M14 3.5V8h4M8 12h7m-7 3h7"/><circle cx="9" cy="18" r="1.2"/></>,
  regulation: <><path d="M12 3 19 6v5c0 4.3-2.8 7.7-7 10-4.2-2.3-7-5.7-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/></>,
  corporate: <><rect x="4" y="7" width="16" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M4 12h16M10 12v2h4v-2"/></>,
  innovation: <><path d="M9 18h6m-5 3h4m-2-19a7 7 0 0 0-4 12.7c.8.6 1 1.2 1 2.3h6c0-1.1.2-1.7 1-2.3A7 7 0 0 0 12 2Z"/></>,
  market: <><path d="M5 4v6m0 4v6m7-16v3m0 4v9m7-16v8m0 4v4"/><path d="M3.5 10h3v4h-3zm7-3h3v5h-3zm7 1h3v6h-3z"/></>,
  analyst: <><circle cx="9" cy="8" r="3.2"/><path d="M3.5 20v-1.3a5.5 5.5 0 0 1 11 0V20h-11Z"/><path d="m18 3.5.9 2 2.1.3-1.5 1.5.4 2.1L18 8.4l-1.9 1 .4-2.1L15 5.8l2.1-.3.9-2Z"/></>,
  operations: <><path d="M3 7h11v10H3zM14 10h4l3 3v4h-7z"/><circle cx="7" cy="18" r="1.5"/><circle cx="18" cy="18" r="1.5"/></>,
  news: <><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/></>,
};

export function NewsCategoryIcon({ category = "", className = "category-icon" }) {
  const value = String(category).toLowerCase();
  const key = /macro|economic|fed|rates|inflation|gdp/.test(value) ? "macro"
    : /earn|result|quarter|revenue/.test(value) ? "earnings"
      : /regulat|legal|policy|government/.test(value) ? "regulation"
        : /merger|acquisition|corporate|dividend|buyback/.test(value) ? "corporate"
          : /product|innovation|technology|launch/.test(value) ? "innovation"
            : /analyst|rating|recommend/.test(value) ? "analyst"
              : /operation|supply|production/.test(value) ? "operations"
                : /market|trading|price/.test(value) ? "market" : "news";
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{categoryIconPaths[key]}</svg>;
}

export function Skeleton({ variant = "rows", count = 4, className = "", width }) {
  if (variant === "inline") return <span className={`skeleton-inline ${className}`} style={width ? { width } : undefined} aria-label="Loading market data"/>;
  if (variant === "stories") return <div className={`skeleton-stories ${className}`} aria-hidden="true">{Array.from({ length: count }, (_, index) => <article className="skeleton-story" key={index}><div className="skeleton-line short"/><div className="skeleton-line headline"/><div className="skeleton-line medium"/><div className="skeleton-line chips"/><div className="skeleton-line short"/></article>)}</div>;
  if (variant === "table") return <div className={`skeleton-table ${className}`} aria-hidden="true"><div className="skeleton-table-head">{Array.from({ length: 6 }, (_, index) => <i key={index}/>)}</div>{Array.from({ length: count }, (_, row) => <div className="skeleton-table-row" key={row}>{Array.from({ length: 6 }, (_, col) => <i key={col}/>)}</div>)}</div>;
  if (variant === "chart") return <div className={`skeleton-chart ${className}`} aria-hidden="true"><div className="skeleton-line short"/><div className="skeleton-chart-area"><i/><i/><i/><i/></div></div>;
  if (variant === "market") return <div className={`skeleton-market ${className}`} aria-hidden="true">{Array.from({ length: count }, (_, index) => <i key={index}/>)}</div>;
  return <div className={`skeleton-rows ${className}`} aria-hidden="true">{Array.from({ length: count }, (_, index) => <div className="skeleton-row" key={index}><i/><span><b/><small/></span><em/></div>)}</div>;
}

export function DataNotice({ loading, error, empty, onRetry, skeleton = "rows", children }) {
  if (loading) return <Skeleton variant={skeleton} count={skeleton === "stories" ? 3 : 5} className="data-skeleton"/>;
  if (error) return <div className="data-notice error-notice"><b>Unable to load data</b><p>{error}</p>{onRetry && <button className="lnk" onClick={onRetry}>Retry</button>}</div>;
  if (empty) return <div className="empty">{empty}</div>;
  return children;
}

export function Drawer({ title, eyebrow, onClose, children }) {
  useEffect(() => { const onKey = (event) => event.key === "Escape" && onClose(); window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [onClose]);
  return <><div className="scrim on" onMouseDown={onClose}/><aside className="dr open" role="dialog" aria-modal="true" aria-label={title}><div className="dh"><span>{eyebrow || "Details"}</span><button className="drawer-close" onClick={onClose} aria-label="Close details">×</button></div><h2>{title}</h2><div className="drawer-content">{children}</div></aside></>;
}

export function SentimentMeter({ score }) {
  if (score == null) return <span className="m">Analysis pending</span>;
  const normalized = Math.max(-1, Math.min(1, Number(score))), tone = normalized > 0.08 ? "up" : normalized < -0.08 ? "dn" : "m";
  const left = normalized >= 0 ? 50 : 50 + normalized * 50, width = Math.abs(normalized) * 50;
  return <span className={`sentiment ${tone}`}><span className="sb" role="img" aria-label={`Sentiment ${normalized.toFixed(2)} from negative one to positive one`}><i style={{ left: `${left}%`, width: `${width}%`, background: normalized >= 0 ? "var(--green)" : "var(--red)" }}/></span><span>Sentiment <b>{normalized > 0 ? "+" : ""}{normalized.toFixed(2)}</b></span></span>;
}

export function PagePagination({ page, totalPages, hasMore = false, onPage, loading = false }) {
  const pages = Math.max(totalPages, 1);
  const start = Math.max(1, Math.min(page - 2, pages - 4));
  const numbers = Array.from({ length: Math.min(5, pages - start + 1) }, (_, i) => start + i);
  return <nav className="page-pagination" aria-label="List pages"><button className="pagination-step" onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Previous page">← Previous</button><div className="pagination-numbers">{numbers.map((number) => <button key={number} className={number === page ? "current" : ""} aria-current={number === page ? "page" : undefined} onClick={() => onPage(number)} aria-label={`Page ${number}`}>{number}</button>)}{hasMore && page >= pages && <span className="pagination-ellipsis">…</span>}</div><button className="pagination-step" onClick={() => onPage(page + 1)} disabled={loading || (!hasMore && page >= totalPages)} aria-label={loading ? "Loading next page" : "Next page"}>{loading ? "Loading…" : "Next →"}</button><span className="pagination-label">Page {page}{hasMore ? " · more available" : ` of ${Math.max(1, totalPages)}`}</span></nav>;
}
