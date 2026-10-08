import { useMemo, useState } from "react";
import { analysisStatus, affectedTickers, eventId, eventTime } from "../services/api";
import { changeClass, cleanText, dateTime, impactScore, money, percent, timeAgo } from "../utils/format";
import { DataNotice, PageHeading, PagePagination, SentimentMeter, Skeleton, TickerMark } from "../components/AppShell";

const label = (value) => (value || "Uncategorized").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
const analyzed = (event) => analysisStatus(event) === "complete";
const analyzedAt = (event) => event.metadata?.analysis_updated_at || eventTime(event);
function CategoryIcon({ category }) {
  const value = String(category || "").toLowerCase();
  const paths = /macro|economic|monetary|inflation|employment|rates|policy|gdp|cpi/.test(value)
    ? <><path d="M3 19h18M5 16V9m5 7V5m5 11v-5m5 5V7"/><path d="m3 7 5-3 5 3 7-5"/></>
    : /analyst|rating|upgrade|downgrade|price_target/.test(value)
      ? <><path d="m12 3 2.3 5 5.5.6-4.1 3.8 1.1 5.4-4.8-2.8-4.8 2.8 1.1-5.4-4.1-3.8 5.5-.6L12 3Z"/><path d="M18 19h3m-1.5-1.5V20.5"/></>
      : /market.?trading|trading|volume/.test(value)
        ? <><path d="M4 19V5m8 14V3m8 16V8"/><path d="M2 9h4m-4 5h4m4-8h4m-4 6h4m4-1h4m-4 6h4"/></>
        : /earning|result|revenue|guidance/.test(value)
          ? <><path d="M4 19V5m0 14h17"/><path d="m7 15 4-4 3 2 6-7"/></>
      : /merger|acquisition|corporate|deal/.test(value)
        ? <><rect x="3" y="7" width="8" height="13" rx="1"/><rect x="13" y="4" width="8" height="16" rx="1"/><path d="M6 10h2m-2 3h2m8-5h2m-2 4h2"/></>
        : /regulation|legal|government/.test(value)
          ? <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="M5 10v6m4-4v7m6-7v7m4-9v6M3 21h18"/></>
          : <><path d="M4 19V5m0 14h16"/><path d="m6 15 4-5 3 2 5-6"/></>;
  return <svg className="category-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths}</svg>;
}
function MiniSparkline({ values = [], change = 0 }) {
  if (values.length < 2) return <span className="spark-placeholder" aria-hidden="true"/>;
  const low = Math.min(...values), span = Math.max(...values) - low || 1;
  const path = values.map((value, index) => `${index ? "L" : "M"}${(index * 56 / (values.length - 1)).toFixed(1)},${(19 - (value - low) * 16 / span).toFixed(1)}`).join(" ");
  return <svg className={`mini-spark ${change < 0 ? "dn" : "up"}`} viewBox="0 0 56 20" aria-label="Recent price trend"><path d={path}/></svg>;
}

export function NewsPage({ events = [], totalEvents, analysisSummary, highImpactEvents, loading, quoteLoading = false, error, refresh, updatedAt, quotes = [], prices = {}, tickers = [], trackedStockCount = 0, onEvent, onTicker, hasMore, onLoadMore, loadingMore }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [source, setSource] = useState("");
  const [age, setAge] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const analyzedEvents = useMemo(() => (events || []).filter((event) => analyzed(event) && event.category && event.sentiment?.impact_score != null), [events]);
  const categories = [...new Set(analyzedEvents.map((event) => event.category).filter(Boolean))].sort();
  const sources = [...new Set(analyzedEvents.map((event) => event.metadata?.source || event.metadata?.provider).filter(Boolean))].sort();
  const stories = useMemo(() => (events || []).filter((event) => {
    const tickerText = affectedTickers(event).map((ticker) => ticker.ticker_id).join(" ");
    const text = `${cleanText(event.headline)} ${cleanText(event.text)} ${tickerText}`.toLowerCase();
    const score = event.sentiment?.score, time = new Date(eventTime(event)).getTime();
    return (!query || text.includes(query.toLowerCase())) && (!category || event.category === category) && (!source || (event.metadata?.source || event.metadata?.provider) === source) && (!sentiment || (score != null && (sentiment === "positive" ? score > 0.1 : sentiment === "negative" ? score < -0.1 : Math.abs(score) <= 0.1))) && (!age || !Number.isFinite(time) || Date.now() - time <= Number(age) * 60_000);
  }).sort((a, b) => new Date(analyzedAt(b)) - new Date(analyzedAt(a)) || new Date(eventTime(b)) - new Date(eventTime(a))), [events, query, category, sentiment, source, age]);
  const affected = useMemo(() => {
    const map = new Map();
    for (const event of analyzedEvents) for (const item of affectedTickers(event)) {
      const previous = map.get(item.ticker_id) || { symbol: item.ticker_id, count: 0, relevance: 0, scored: 0 };
      previous.count += 1;
      if (analyzed(event) && item.relevance_score != null) { previous.relevance += Number(item.relevance_score) || 0; previous.scored += 1; }
      map.set(item.ticker_id, previous);
    }
    return [...map.values()].sort((a, b) => b.count - a.count || b.relevance - a.relevance).slice(0, 6);
  }, [analyzedEvents]);
  const movers = useMemo(() => (quotes || []).filter((quote) => quote.change != null && quote.price != null && Number.isFinite(Number(quote.change)) && Number.isFinite(Number(quote.price))), [quotes]);
  const gainers = [...movers].sort((a, b) => Number(b.change) - Number(a.change)).slice(0, 4);
  const losers = [...movers].sort((a, b) => Number(a.change) - Number(b.change)).slice(0, 4);
  const breadth = useMemo(() => movers.reduce((counts, quote) => {
    const change = Number(quote.change);
    if (change > 0) counts.advancing += 1;
    else if (change < 0) counts.declining += 1;
    else counts.flat += 1;
    return counts;
  }, { advancing: 0, declining: 0, flat: 0 }), [movers]);
  const sentimentPulse = useMemo(() => analyzedEvents.reduce((pulse, event) => {
    const score = Number(event.sentiment?.score);
    if (!Number.isFinite(score)) return pulse;
    if (score > 0.1) pulse.positive += 1;
    else if (score < -0.1) pulse.negative += 1;
    else pulse.neutral += 1;
    pulse.total += 1;
    pulse.mean += score;
    return pulse;
  }, { positive: 0, neutral: 0, negative: 0, total: 0, mean: 0 }), [analyzedEvents]);
  const highImpactStories = useMemo(() => (Array.isArray(highImpactEvents) ? highImpactEvents : analyzedEvents.filter((event) => Number(event.sentiment?.impact_score) >= 0.75)).slice().sort((a, b) => Number(b.sentiment?.impact_score) - Number(a.sentiment?.impact_score)).slice(0, 3), [analyzedEvents, highImpactEvents]);
  const economicStories = analyzedEvents.filter((event) => /macro|economic|monetary|inflation|employment|rates|central.?bank|policy|gdp|cpi|pmi/i.test(`${event.category || ""} ${event.headline || ""}`)).sort((a, b) => Number(b.sentiment?.impact_score || 0) - Number(a.sentiment?.impact_score || 0)).slice(0, 3);
  // Numbered links only represent rows already in memory. “Next” incrementally
  // loads the next API page, avoiding links that jump into unloaded data.
  const totalPages = Math.max(1, Math.ceil(stories.length / pageSize));
  const pageStories = stories.slice((page - 1) * pageSize, page * pageSize);
  const changePage = (nextPage) => {
    if ((nextPage - 1) * pageSize >= events.length && hasMore) onLoadMore?.();
    setPage(nextPage);
  };
  return <>
    <PageHeading kicker="LIVE NEWS & MARKET INTELLIGENCE" title="Market Pulse" description="News headlines with recorded sentiment, affected tickers, and market prices." actions={<span className="updated-label"><i className="dot up"/> {updatedAt ? `Updated ${timeAgo(updatedAt)}` : "Waiting for feed"}</span>} />
    <div className="feed-heading"><div><span className="live-badge"><i/> LIVE · 30S REFRESH</span><span className="feed-count">{events.length.toLocaleString()} loaded · {(analysisSummary?.analyzed_count ?? totalEvents ?? analyzedEvents.length).toLocaleString()} analyzed total · {(analysisSummary?.queued_count ?? 0).toLocaleString()} queued · {(analysisSummary?.database_count ?? totalEvents ?? events.length).toLocaleString()} total in DB{analysisSummary?.other_count ? ` · ${analysisSummary.other_count.toLocaleString()} unclassified` : ""}</span></div><span className="m">{loading ? "Refreshing feed…" : "Newest analyzed stories first · source time shown on each item"}</span></div>
    <section className="filters" aria-label="News filters"><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="Search headlines or ticker" aria-label="Search headlines or tickers"/><select value={category} onChange={(event) => { setCategory(event.target.value); setPage(1); }} aria-label="Category"><option value="">All categories</option>{categories.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select><select value={sentiment} onChange={(event) => { setSentiment(event.target.value); setPage(1); }} aria-label="Sentiment"><option value="">All sentiment</option><option value="positive">Positive</option><option value="neutral">Neutral</option><option value="negative">Negative</option></select><select value={source} onChange={(event) => { setSource(event.target.value); setPage(1); }} aria-label="Source"><option value="">All sources</option>{sources.map((item) => <option key={item}>{item}</option>)}</select><select value={age} onChange={(event) => { setAge(event.target.value); setPage(1); }} aria-label="Time range"><option value="">Any time</option><option value="60">Last hour</option><option value="240">Last 4 hours</option><option value="1440">Last 24 hours</option></select></section>
    <div className="cols"><section className="feed-column"><DataNotice skeleton="stories" loading={loading && !events.length} error={error && !events.length ? error : ""} onRetry={refresh} empty={!stories.length && !hasMore ? events.length ? "No stories match these filters." : "No news events are available from the service." : null}>
      {pageStories.map((event, index) => {
        const id = eventId(event), affectedStocks = affectedTickers(event), created = eventTime(event), status = analysisStatus(event), ready = analyzed(event), score = event.sentiment?.score;
        return <article className={`row ${Number(event.sentiment?.impact_score) >= 0.7 ? "hi" : ""}`} key={id || `${created}-${event.headline}`}>
          <div className="meta"><time>{dateTime(created)}</time><span>{timeAgo(created)}</span><span>{event.metadata?.source || event.metadata?.provider || "News wire"}</span>{index === 0 && <mark>NEWEST</mark>}<span className="cat"><CategoryIcon category={event.category}/>{label(event.category)}</span></div>
          <h3><button className="hl" onClick={() => onEvent(event)}>{cleanText(event.headline) || "Headline unavailable"}</button></h3>
          {event.text && <p>{cleanText(event.text).slice(0, 240)}{cleanText(event.text).length > 240 ? "…" : ""}</p>}
          <div className="chips">{affectedStocks.length ? affectedStocks.slice(0, 7).map((ticker) => { const quote = prices[ticker.ticker_id]; const relevance = !ready ? "Relevance pending" : ticker.relevance_score == null ? "Relevance n/a" : `${Math.round(ticker.relevance_score * 100)}% relevant`; return <button className="chip" key={ticker.ticker_id} onClick={() => onTicker(ticker.ticker_id)}><TickerMark symbol={ticker.ticker_id} tickers={tickers}/><b>{ticker.ticker_id}</b><span className="chip-relevance">{relevance}</span><span className="chip-market-value">{quote?.price != null ? money(quote.price, quote.currency || "USD") : quoteLoading ? <Skeleton variant="inline" width="46px"/> : "Price unavailable"}</span><span className={`chip-market-change ${quote?.change == null ? "pending" : changeClass(quote.change)}`}>{quote?.change == null ? quoteLoading ? <Skeleton variant="inline" width="30px"/> : "—" : percent(quote.change, 2, false)}</span></button>; }) : <span className="m">No affected tickers recorded</span>}</div>
          <div className="ind"><SentimentMeter score={score}/><span>Impact <b>{!ready ? "Pending" : event.sentiment?.impact_score == null ? "Not recorded" : impactScore(event.sentiment.impact_score)}</b></span><span>Category <b>{label(event.category)}</b></span>{String(status).toLowerCase() !== "complete" && <span className="m">{status.replaceAll("_", " ")}</span>}</div>
          {event.url && <a className="lnk" href={event.url} target="_blank" rel="noreferrer">Open source ↗</a>}
        </article>;
      })}
      {(stories.length > 0 || hasMore) && <PagePagination page={page} totalPages={totalPages} hasMore={hasMore} onPage={changePage} loading={loadingMore}/>}
    </DataNotice></section>
    <aside className="side">
      <section className="side-panel"><h2>Most affected stocks</h2>{affected.length ? affected.map((item) => { const quote = prices[item.symbol]; return <button className="ar" key={item.symbol} onClick={() => onTicker(item.symbol)}><span className="stock-mention"><b><TickerMark symbol={item.symbol} tickers={tickers}/>{item.symbol}</b><small>{item.count} analyzed stor{item.count === 1 ? "y" : "ies"}{item.scored ? ` · ${item.relevance.toFixed(2)} relevance` : ""}</small></span><span className="stock-signal">{quote ? <><b>{quote.price != null ? money(quote.price, quote.currency || "USD") : quoteLoading ? <Skeleton variant="inline" width="48px"/> : "—"}</b><small className={changeClass(quote.change)}>{quote.change != null ? percent(quote.change, 2, false) : quoteLoading ? <Skeleton variant="inline" width="34px"/> : "—"}</small></> : quoteLoading ? <><Skeleton variant="inline" width="48px"/><Skeleton variant="inline" width="34px"/></> : <small className="m">Price unavailable</small>}</span><MiniSparkline values={quote?.sparkline} change={quote?.change}/></button>; }) : <p className="m">No affected tickers recorded yet.</p>}</section>
      <section className="side-panel"><h2>Top gainers</h2>{gainers.length ? gainers.map((quote) => <button className="mover-row" key={quote.ticker} onClick={() => onTicker(quote.ticker)}><span><b>{quote.ticker}</b><small>{money(quote.price, quote.currency || "USD")}</small></span><MiniSparkline values={quote.sparkline} change={quote.change}/><strong className="positive">{percent(quote.change, 2, false)}</strong></button>) : quoteLoading ? <Skeleton variant="rows" count={3}/> : <p className="m">Live price changes are not available.</p>}</section>
      <section className="side-panel"><h2>Top losers</h2>{losers.length ? losers.map((quote) => <button className="mover-row" key={quote.ticker} onClick={() => onTicker(quote.ticker)}><span><b>{quote.ticker}</b><small>{money(quote.price, quote.currency || "USD")}</small></span><MiniSparkline values={quote.sparkline} change={quote.change}/><strong className="negative">{percent(quote.change, 2, false)}</strong></button>) : quoteLoading ? <Skeleton variant="rows" count={3}/> : <p className="m">Live price changes are not available.</p>}</section>
      <section className="side-panel"><h2>Market breadth</h2><div className="breadth-counts">{quoteLoading ? <><span><b><Skeleton variant="inline" width="22px"/></b><small>Advancing</small></span><span><b><Skeleton variant="inline" width="22px"/></b><small>Unchanged</small></span><span><b><Skeleton variant="inline" width="22px"/></b><small>Declining</small></span></> : <><span><b className="positive">{breadth.advancing}</b><small>Advancing</small></span><span><b>{breadth.flat}</b><small>Unchanged</small></span><span><b className="negative">{breadth.declining}</b><small>Declining</small></span></>}</div>{quoteLoading ? <Skeleton variant="inline" className="breadth-skeleton"/> : <div className="breadth-bar" role="img" aria-label={`${breadth.advancing} advancing, ${breadth.flat} unchanged, ${breadth.declining} declining across ${trackedStockCount || 100} tracked index stocks`}><i className="breadth-up" style={{ flexGrow: breadth.advancing }}/><i className="breadth-flat" style={{ flexGrow: breadth.flat }}/><i className="breadth-down" style={{ flexGrow: breadth.declining }}/></div>}<small className="module-note">Across {trackedStockCount || 100} tracked index stocks · {quoteLoading ? "Loading live price changes" : `${movers.length} with live price changes`}</small></section>
      <section className="side-panel"><h2>Sentiment pulse</h2><div className="sentiment-cards"><span><b className="positive">{sentimentPulse.positive}</b><small>Positive</small></span><span><b>{sentimentPulse.neutral}</b><small>Neutral</small></span><span><b className="negative">{sentimentPulse.negative}</b><small>Negative</small></span></div><div className="pulse-average"><span>Average score</span><b className={sentimentPulse.mean >= 0 ? "positive" : "negative"}>{sentimentPulse.total ? (sentimentPulse.mean / sentimentPulse.total).toFixed(2) : "—"}</b></div><small className="module-note">From {sentimentPulse.total} scored stories in the loaded feed</small></section>
      <section className="side-panel"><h2>High-impact headlines</h2>{highImpactStories.length ? highImpactStories.map((event) => <button className="economic-row impact-row" key={eventId(event) || event.headline} onClick={() => onEvent(event)}><b>{cleanText(event.headline)}</b><small>{label(event.category)} · model impact {impactScore(event.sentiment.impact_score)} · {timeAgo(eventTime(event))}</small></button>) : <p className="m">No analyzed stories in the database meet the 7.5/10 model impact threshold.</p>}</section>
      <section className="side-panel"><h2>Top economic events</h2>{economicStories.length ? economicStories.map((event) => <button className="economic-row" key={eventId(event) || event.headline} onClick={() => onEvent(event)}><b>{cleanText(event.headline)}</b><small>{label(event.category)} · impact {impactScore(event.sentiment.impact_score)} · {timeAgo(eventTime(event))}</small></button>) : <p className="m">No analyzed economic events in the current feed.</p>}</section>
      {(quotes.length > 0 || quoteLoading) && <section className="side-panel"><h2>Tracked prices</h2>{quotes.length ? quotes.slice(0, 5).map((quote) => <button className="ar tracked-price" key={quote.ticker} onClick={() => onTicker(quote.ticker)}><span className="stock-mention"><b><TickerMark symbol={quote.ticker} tickers={tickers}/>{quote.ticker}</b><small>{quote.company || "Tracked portfolio holding"}</small></span><span className="stock-signal"><b>{money(quote.price, quote.currency || "USD")}</b><small className={changeClass(quote.change)}>{percent(quote.change, 2, false)}</small></span><MiniSparkline values={quote.sparkline} change={quote.change}/></button>) : <Skeleton variant="rows" count={4}/>}</section>}
    </aside></div>
  </>;
}
