export const money = (value, currency = "USD", compact = false) => {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat(undefined, { style: "currency", currency, notation: compact ? "compact" : "standard", maximumFractionDigits: compact ? 1 : 2 }).format(value);
};
export const number = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
export const impactScore = (value, digits = 1) => value == null || !Number.isFinite(Number(value)) ? "—" : `${number(Number(value) * 10, digits)}/10`;
export const percent = (value, digits = 2, isRatio = true) => value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value) >= 0 ? "+" : "−"}${Math.abs(Number(value) * (isRatio ? 100 : 1)).toFixed(digits)}%`;
export const signed = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value) >= 0 ? "+" : "−"}${Math.abs(Number(value)).toFixed(digits)}`;
export const dateTime = (value) => {
  if (!value) return "—";
  // PyMongo returns stored UTC datetimes as naive values. Treat ISO strings
  // without an explicit zone as UTC so browsers do not show UTC wall time as
  // the user's local time (e.g. 13:30 UTC appearing as 13:30 in India).
  const normalized = typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)
    && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? `${value}Z` : value;
  const timestamp = new Date(normalized);
  return Number.isFinite(timestamp.getTime()) ? timestamp.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Time unavailable";
};
export const timeAgo = (value) => {
  if (!value) return "Time unavailable";
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Time unavailable";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
};
export const changeClass = (value) => Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "neutral";
export const tickerOf = (position) => position?.ticker_id || position?.ticker || "";
export const formatReason = (value) => {
  const reason = String(value || "Scheduled rebalance").replace(/^strategy:/i, "").replaceAll("_", " ").trim();
  return /^volume spike0$/i.test(reason) ? "Volume spike" : reason;
};
export const cleanText = (value) => {
  if (value == null) return "";
  const source = String(value).replace(/<\/?(?:p|div|br|li|ul|ol|a|span|strong|b|em|i|h\d)[^>]*>/gi, " ").replace(/<[^>]*>/g, " ");
  const decoder = document.createElement("textarea");
  decoder.innerHTML = source;
  return decoder.value.replace(/\s+/g, " ").trim();
};
