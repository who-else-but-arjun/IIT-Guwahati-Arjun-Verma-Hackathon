import { useCallback, useEffect, useState } from "react";

function readSnapshot(cacheKey) {
  if (!cacheKey) return null;
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(`crisil:snapshot:${cacheKey}`) || "null");
    return saved && Date.now() - saved.savedAt < 24 * 60 * 60 * 1000 ? saved.data : null;
  } catch { return null; }
}

export function usePolling(loader, interval = 0, dependencies = [], cacheKey = "") {
  const [data, setData] = useState(() => readSnapshot(cacheKey));
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(() => readSnapshot(cacheKey) == null);
  const [updatedAt, setUpdatedAt] = useState(null);
  useEffect(() => {
    if (!cacheKey) return;
    const snapshot = readSnapshot(cacheKey);
    if (snapshot != null) { setData(snapshot); setLoading(false); }
  }, [cacheKey]);
  const refresh = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const value = await loader();
      setData(value); setError(""); setUpdatedAt(new Date());
      if (cacheKey) {
        try { window.sessionStorage.setItem(`crisil:snapshot:${cacheKey}`, JSON.stringify({ savedAt: Date.now(), data: value })); } catch { /* Storage is an optional fast first paint. */ }
      }
    } catch (err) { setError(err.message || "Could not load data."); }
    finally { setLoading(false); }
  // loader identity is intentionally controlled by the caller's dependencies.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, cacheKey]);
  useEffect(() => {
    refresh();
    if (!interval) return undefined;
    const id = window.setInterval(refresh, interval);
    const onVisible = () => { if (document.visibilityState === "visible") refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [refresh, interval]);
  return { data, error, loading, updatedAt, refresh, setData };
}
