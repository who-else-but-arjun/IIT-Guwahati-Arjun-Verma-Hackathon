import { useEffect, useMemo, useRef, useState } from "react";
import { PageHeading, DataNotice } from "../components/AppShell";

const stableIndex = (value) => [...value].reduce((n, char) => ((n * 31) + char.charCodeAt(0)) >>> 0, 17);

export function UniversePage({ tickers = [], loading, error, refresh, events = [], portfolios = [], onTicker, focusTicker = "" }) {
  const canvasRef = useRef(null), stateRef = useRef({ yaw: 0.45, pitch: -0.28, zoom: 1, drag: null, selected: "", pointer: null, lastNodes: [] });
  const [search, setSearch] = useState(focusTicker);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [heldOnly, setHeldOnly] = useState(false);
  const [newsOnly, setNewsOnly] = useState(false);
  const [correlationsOn, setCorrelationsOn] = useState(true);
  const [newsLinksOn, setNewsLinksOn] = useState(true);
  const [threshold, setThreshold] = useState(0.45);
  const [rotation, setRotation] = useState(true);
  const nodes = useMemo(() => {
    const positions = new Map();
    for (const portfolio of portfolios) for (const pos of portfolio.positions || []) {
      const ticker = pos.ticker_id;
      const old = positions.get(ticker) || { weight: 0, market_value: 0, portfolios: [] };
      old.weight = Math.max(old.weight, Number(pos.weight) || 0); old.market_value = Math.max(old.market_value, Number(pos.market_value) || 0); old.portfolios.push(portfolio.name); positions.set(ticker, old);
    }
    const newsSymbols = new Set();
    for (const event of events) for (const related of event.relevant_tickers || []) newsSymbols.add(typeof related === "string" ? related : related.ticker_id);
    return tickers.map((row) => {
      const identity = row.ticker_name || {};
      const symbol = identity.ticker_id;
      const held = positions.get(symbol);
      const index = stableIndex(symbol);
      const count = Math.max(1, tickers.length);
      const i = tickers.findIndex((item) => item.ticker_name?.ticker_id === symbol);
      const phi = Math.acos(1 - 2 * (i + 0.5) / count), theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const score = row.ticker_score?.sentiment;
      return { symbol, name: identity.company_name || symbol, x: Math.cos(theta) * Math.sin(phi), y: Math.cos(phi), z: Math.sin(theta) * Math.sin(phi), held, news: newsSymbols.has(symbol), score: score?.score, impact: score?.impact_score, updated: row.updated_at, graph: row.ticker_graph?.correlations || {}, seed: index };
    }).filter((node) => node.symbol);
  }, [tickers, portfolios, events]);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.symbol, node])), [nodes]);
  const newsEdges = useMemo(() => {
    const links = new Set();
    for (const event of events) {
      const names = [...new Set((event.relevant_tickers || []).map((item) => typeof item === "string" ? item : item.ticker_id).filter((symbol) => nodeMap.has(symbol)))].slice(0, 12);
      for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) links.add([names[i], names[j]].sort().join("|"));
    }
    return links;
  }, [events, nodeMap]);
  const visibleNodes = useMemo(() => nodes.filter((node) => (!heldOnly || node.held) && (!newsOnly || node.news)), [nodes, heldOnly, newsOnly]);
  const focus = (symbol) => {
    const match = nodes.find((node) => node.symbol.toLowerCase() === symbol.trim().toLowerCase() || node.name.toLowerCase().includes(symbol.trim().toLowerCase()));
    if (!match) return false;
    setSelectedSymbol(match.symbol); stateRef.current.selected = match.symbol; stateRef.current.yaw = Math.PI / 2 - Math.atan2(match.z, match.x); stateRef.current.pitch = -Math.asin(match.y); stateRef.current.zoom = 1.65; setRotation(false); return true;
  };
  useEffect(() => { if (focusTicker && nodes.some((node) => node.symbol === focusTicker)) { setSearch(focusTicker); focus(focusTicker); } }, [focusTicker, nodes]);
  useEffect(() => {
    const canvas = canvasRef.current, ctx = canvas?.getContext("2d"); if (!canvas || !ctx) return undefined;
    let raf = 0, width = 0, height = 0, ratio = 1, last = performance.now();
    const resize = () => { const box = canvas.getBoundingClientRect(); width = box.width; height = box.height; ratio = window.devicePixelRatio || 1; canvas.width = width * ratio; canvas.height = height * ratio; ctx.setTransform(ratio, 0, 0, ratio, 0, 0); };
    const observer = new ResizeObserver(resize); observer.observe(canvas); resize();
    const draw = (now) => {
      const elapsed = Math.min(0.05, (now - last) / 1000); last = now;
      const s = stateRef.current; if (rotation && !s.drag && !s.selected) s.yaw += elapsed * 0.075;
      ctx.clearRect(0, 0, width, height);
      const cx = width * 0.5, cy = height * 0.5, scale = Math.min(width, height) * 0.34 * s.zoom;
      const ca = Math.cos(s.yaw), sa = Math.sin(s.yaw), cp = Math.cos(s.pitch), sp = Math.sin(s.pitch);
      const dark = document.documentElement.dataset.theme === "dark";
      const visible = nodes.filter((node) => (!heldOnly || node.held) && (!newsOnly || node.news));
      const project = (node) => { const rx = node.x * ca - node.z * sa, rz = node.x * sa + node.z * ca; const ry = node.y * cp - rz * sp; const depth = node.y * sp + rz * cp; const perspective = 1 / (1.7 - depth * 0.45); return { x: cx + rx * scale * perspective, y: cy - ry * scale * perspective, depth, perspective }; };
      const projected = new Map(visible.map((node) => [node.symbol, project(node)]));
      // A restrained perspective floor gives the network depth without adding
      // another chart panel or competing with the connected stock nodes.
      ctx.strokeStyle = dark ? "#292a2c" : "#e4e4e1"; ctx.lineWidth = 0.65; ctx.setLineDash([]);
      for (let n = -4; n <= 4; n++) {
        const offset = n * 0.34, fromX = project({ x: offset, y: -1.25, z: -1.35 }), toX = project({ x: offset, y: -1.25, z: 1.35 });
        const fromZ = project({ x: -1.35, y: -1.25, z: offset }), toZ = project({ x: 1.35, y: -1.25, z: offset });
        ctx.beginPath(); ctx.moveTo(fromX.x, fromX.y); ctx.lineTo(toX.x, toX.y); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(fromZ.x, fromZ.y); ctx.lineTo(toZ.x, toZ.y); ctx.stroke();
      }
      const edges = [];
      if (correlationsOn) for (const node of visible) for (const [neighbor, correlation] of Object.entries(node.graph)) {
        const target = nodeMap.get(neighbor); if (target && node.symbol < neighbor && visible.includes(target) && Math.abs(correlation) >= threshold) edges.push({ from: node, to: target, weight: Math.abs(correlation), kind: "correlation", correlation });
      }
      if (newsLinksOn) for (const pair of newsEdges) { const [from, to] = pair.split("|"); const a = nodeMap.get(from), b = nodeMap.get(to); if (a && b && visible.includes(a) && visible.includes(b)) edges.push({ from: a, to: b, weight: 0.5, kind: "news" }); }
      for (const edge of edges) {
        const a = projected.get(edge.from.symbol), b = projected.get(edge.to.symbol); if (!a || !b) continue;
        const selectedDim = s.selected && edge.from.symbol !== s.selected && edge.to.symbol !== s.selected;
        ctx.globalAlpha = selectedDim ? 0.10 : Math.max(0.16, Math.min(0.75, edge.weight)); ctx.strokeStyle = edge.kind === "news" ? "#d92f39" : "#9da3ad"; ctx.lineWidth = edge.kind === "news" ? 1.15 : 0.55 + edge.weight * 1.4; ctx.setLineDash(edge.kind === "news" ? [4, 4] : []); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      const drawOrder = [...visible].sort((a, b) => projected.get(a.symbol).depth - projected.get(b.symbol).depth);
      const hitNodes = [];
      for (const node of drawOrder) {
        const p = projected.get(node.symbol), held = node.held, focused = s.selected === node.symbol, faded = s.selected && !focused && !node.graph[s.selected] && !nodeMap.get(s.selected)?.graph[node.symbol] && !newsEdges.has([node.symbol, s.selected].sort().join("|"));
        const radius = Math.max(3, (held ? 5 + Math.sqrt(Math.max(0, node.held.weight * 100)) * 1.6 : 4.2) * p.perspective);
        ctx.globalAlpha = faded ? 0.22 : 1;
        const gradient = ctx.createRadialGradient(p.x - radius * .32, p.y - radius * .36, 1, p.x, p.y, radius * 1.4); gradient.addColorStop(0, dark ? (held ? "#ffffff" : "#9a9da2") : (held ? "#555962" : "#ffffff")); gradient.addColorStop(.68, dark ? (held ? "#d4d4d0" : "#33363a") : (held ? "#181a20" : node.news ? "#f4dfe0" : "#fbfbfc")); gradient.addColorStop(1, dark ? (held ? "#85878b" : node.news ? "#d92f39" : "#71757c") : (held ? "#0d0e11" : node.news ? "#d92f39" : "#8c919a")); ctx.fillStyle = gradient; ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = focused ? "#d92f39" : held ? (dark ? "#eeeeeb" : "#17191e") : node.news ? "#d92f39" : (dark ? "#858990" : "#8b9099"); ctx.lineWidth = focused ? 2.8 : 1.15; ctx.beginPath(); ctx.arc(p.x, p.y, radius + (focused ? 2 : 0), 0, Math.PI * 2); ctx.stroke();
        if (node.news && !focused) { ctx.strokeStyle = "#d92f39"; ctx.globalAlpha = faded ? .16 : .85; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(p.x, p.y, radius + 3, 0, Math.PI * 2); ctx.stroke(); }
        ctx.globalAlpha = faded ? .2 : 1;
        if (focused || visible.length < 45 || p.depth > .35) { ctx.font = `${focused ? "700" : "600"} ${focused ? 11 : 9}px Inter, ui-sans-serif, sans-serif`; ctx.textAlign = "center"; ctx.fillStyle = dark ? "#f2f2ef" : "#17191e"; ctx.fillText(node.symbol, p.x, p.y + radius + 13); }
        hitNodes.push({ symbol: node.symbol, x: p.x, y: p.y, radius: Math.max(radius, 9), depth: p.depth });
      }
      s.lastNodes = hitNodes; ctx.globalAlpha = 1;
      const pointer = s.pointer && hitNodes.find((node) => Math.hypot(node.x - s.pointer.x, node.y - s.pointer.y) < node.radius + 4);
      canvas.style.cursor = s.drag ? "grabbing" : pointer ? "pointer" : "grab";
      if (pointer) { const node = nodeMap.get(pointer.symbol); ctx.font = "600 11px Inter, sans-serif"; const label = `${node.symbol} · ${node.name}`; const w = ctx.measureText(label).width + 22, x = Math.min(width - w - 10, Math.max(10, pointer.x - w / 2)), y = Math.max(12, pointer.y - 40); ctx.fillStyle = "#17191e"; ctx.beginPath(); ctx.roundRect(x, y, w, 27, 5); ctx.fill(); ctx.fillStyle = "white"; ctx.textAlign = "left"; ctx.fillText(label, x + 11, y + 18); }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    const pointers = new Map();
    let pinch = null;
    const pointerDown = (e) => { canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); setRotation(false); if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y), zoom: stateRef.current.zoom }; stateRef.current.drag = null; } else { stateRef.current.drag = { x: e.clientX, y: e.clientY, moved: 0 }; } };
    const pointerMove = (e) => { const rect = canvas.getBoundingClientRect(), s = stateRef.current; if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); if (pointers.size >= 2 && pinch) { const [a, b] = [...pointers.values()]; const distance = Math.hypot(a.x - b.x, a.y - b.y); s.zoom = Math.max(.65, Math.min(2.6, pinch.zoom * distance / Math.max(pinch.distance, 1))); s.drag = null; } else if (s.drag) { const dx = e.clientX - s.drag.x, dy = e.clientY - s.drag.y; s.drag.x = e.clientX; s.drag.y = e.clientY; s.drag.moved += Math.abs(dx) + Math.abs(dy); s.yaw += dx * .006; s.pitch = Math.max(-1.35, Math.min(1.35, s.pitch + dy * .005)); } s.pointer = { x: e.clientX - rect.left, y: e.clientY - rect.top }; };
    const hitAt = (e) => { const rect = canvas.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top; return [...stateRef.current.lastNodes].reverse().find((node) => Math.hypot(node.x - x, node.y - y) < node.radius + 5); };
    const pointerUp = (e) => { const s = stateRef.current, drag = s.drag, wasPinching = Boolean(pinch); pointers.delete(e.pointerId); if (pointers.size < 2) pinch = null; s.drag = null; if (pointers.size === 1) { const remaining = [...pointers.values()][0]; s.drag = { ...remaining, moved: 9 }; } if (!wasPinching && drag && drag.moved < 8) { const hit = hitAt(e); if (hit) { s.selected = hit.symbol; setSelectedSymbol(hit.symbol); } else { s.selected = ""; setSelectedSymbol(""); } } };
    const doubleClick = (e) => { const hit = hitAt(e); if (!hit) return; stateRef.current.selected = hit.symbol; setSelectedSymbol(hit.symbol); onTicker?.(hit.symbol); };
    const wheel = (e) => { e.preventDefault(); stateRef.current.zoom = Math.max(.65, Math.min(2.6, stateRef.current.zoom * (e.deltaY < 0 ? 1.08 : .92))); setRotation(false); };
    canvas.addEventListener("pointerdown", pointerDown); canvas.addEventListener("pointermove", pointerMove); canvas.addEventListener("pointerup", pointerUp); canvas.addEventListener("pointercancel", pointerUp); canvas.addEventListener("dblclick", doubleClick); canvas.addEventListener("wheel", wheel, { passive: false });
    return () => { cancelAnimationFrame(raf); observer.disconnect(); canvas.removeEventListener("pointerdown", pointerDown); canvas.removeEventListener("pointermove", pointerMove); canvas.removeEventListener("pointerup", pointerUp); canvas.removeEventListener("pointercancel", pointerUp); canvas.removeEventListener("dblclick", doubleClick); canvas.removeEventListener("wheel", wheel); };
  }, [nodes, nodeMap, newsEdges, heldOnly, newsOnly, correlationsOn, newsLinksOn, threshold, rotation, onTicker]);
  const doSearch = (event) => { event.preventDefault(); if (!search.trim()) return; if (!focus(search)) setSearch(search); };
  const clearSelected = () => { setSelectedSymbol(""); stateRef.current.selected = ""; };
  return <>
    <PageHeading kicker="INTERACTIVE MARKET MAP" title="Stock Universe" description="Explore persisted correlation links and stocks mentioned together in analyzed stories." actions={<span className="updated-label">{nodes.length} stored ticker records</span>} />
    <div className="universe-layout"><section className="panel universe-panel"><DataNotice skeleton="chart" loading={loading} error={error} onRetry={refresh} empty={nodes.length ? null : "No ticker graph records are stored yet. Run the price retrieval job to save correlation data, or wait for news-linked tickers to be persisted."}><><div className="universe-canvas-wrap"><canvas ref={canvasRef} className="universe-canvas" aria-label="Interactive 3D stock universe graph. Drag to rotate, use the wheel to zoom, click to highlight, and double-click a stock for details."/><div className="universe-overlay-toolbar"><form className="universe-search" onSubmit={doSearch}><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a stock in the graph"/><button>Focus</button></form><button className={`rotation-toggle ${rotation ? "on" : ""}`} onClick={() => setRotation(!rotation)}><i/>{rotation ? "Auto rotate" : "Rotation paused"}</button><button className="icon-button" onClick={() => { stateRef.current.zoom = 1; stateRef.current.yaw = .45; stateRef.current.pitch = -.28; setRotation(true); clearSelected(); }} title="Reset graph">⟲</button></div><aside className="panel graph-controls"><div className="section-kicker">GRAPH FILTERS</div><h2>Shape the view</h2><label className="toggle-row"><span><b>Portfolio holdings</b><small>Show stocks held in either strategy</small></span><input type="checkbox" checked={heldOnly} onChange={(e) => setHeldOnly(e.target.checked)}/></label><label className="toggle-row"><span><b>News-affected stocks</b><small>Stocks connected to loaded events</small></span><input type="checkbox" checked={newsOnly} onChange={(e) => setNewsOnly(e.target.checked)}/></label><div className="control-group"><label className="toggle-row"><span><b>Correlation links</b><small>Stored signed return correlations</small></span><input type="checkbox" checked={correlationsOn} onChange={(e) => setCorrelationsOn(e.target.checked)}/></label>{correlationsOn && <div className="range-control"><span>Minimum strength <b>{threshold.toFixed(2)}</b></span><input type="range" min="0.1" max="0.9" step="0.05" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}/></div>}</div><label className="toggle-row"><span><b>News connections</b><small>Stocks named in the same event</small></span><input type="checkbox" checked={newsLinksOn} onChange={(e) => setNewsLinksOn(e.target.checked)}/></label><div className="graph-caveat">Correlations and shared news mentions show relationships, not proof that one stock caused another to move.</div></aside><div className="canvas-hint">DRAG TO ROTATE <i>·</i> SCROLL TO ZOOM <i>·</i> DOUBLE-CLICK A STOCK FOR DETAILS</div><div className="canvas-count">{visibleNodes.length} stocks <i>·</i> {correlationsOn ? nodes.reduce((count, node) => count + Object.entries(node.graph).filter(([symbol, value]) => node.symbol < symbol && nodeMap.has(symbol) && Math.abs(value) >= threshold).length, 0) : 0} correlation links <i>·</i> {newsLinksOn ? newsEdges.size : 0} story links</div></div><div className="graph-legend"><span><i className="legend-node held"/>Held · size shows portfolio weight</span><span><i className="legend-node"/>Tracked ticker</span><span><i className="legend-node story"/>Mentioned in current news</span><span><i className="legend-edge"/>Correlation · gray</span><span><i className="legend-edge story"/>Same analyzed story · red dashed</span></div></></DataNotice></section></div>
  </>;
}
