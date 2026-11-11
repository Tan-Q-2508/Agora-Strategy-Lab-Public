/**
 * Number formatting per GLOSSARY.md: India uses lakh/crore grouping (₹12,34,567.89,
 * "₹12.3 L", "₹1.2 Cr"); US uses $1,234,567.89 ("$1.2M"). Percentages always carry a
 * sign and use a true minus (−).
 */
export type Currency = "INR" | "USD";

const MINUS = "−";

function withMinus(text: string): string {
  return text.replace("-", MINUS);
}

export function formatMoney(value: number, currency: Currency, decimals = 2): string {
  const locale = currency === "INR" ? "en-IN" : "en-US";
  const text = new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
  return withMinus(text);
}

export function formatSignedMoney(value: number, currency: Currency, decimals = 2): string {
  const body = formatMoney(Math.abs(value), currency, decimals);
  if (value > 0) return `+${body}`;
  if (value < 0) return `${MINUS}${body}`;
  return body;
}

export function formatCompactMoney(value: number, currency: Currency): string {
  const sign = value < 0 ? MINUS : "";
  const abs = Math.abs(value);
  if (currency === "INR") {
    if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7)} Cr`;
    if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5)} L`;
    return `${sign}${formatMoney(abs, "INR", 0)}`;
  }
  if (abs >= 1e9) return `${sign}$${trim(abs / 1e9)}B`;
  if (abs >= 1e6) return `${sign}$${trim(abs / 1e6)}M`;
  if (abs >= 1e3) return `${sign}$${trim(abs / 1e3)}K`;
  return `${sign}${formatMoney(abs, "USD", 0)}`;
}

function trim(n: number): string {
  return n >= 100 ? n.toFixed(0) : n.toFixed(1).replace(/\.0$/, "");
}

/** `ratio` 0.042 → "+4.2%". */
export function formatPercent(ratio: number, decimals = 1): string {
  const pct = (ratio * 100).toFixed(decimals);
  if (ratio > 0) return `+${pct}%`;
  if (ratio < 0) return `${MINUS}${pct.slice(1)}%`;
  return `${pct}%`;
}

/** "4h 12m", "13h 40m", "2d 3h", "45s". */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

export const MARKET_TZ = { IN: "Asia/Kolkata", US: "America/New_York" } as const;
export const MARKET_CURRENCY = { IN: "INR", US: "USD" } as const;

/** "12 Mar 2024" in the given timezone. */
export function formatDate(ms: number, timeZone = "UTC"): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone }).format(ms);
}

/** "12 Mar 2024, 09:15" in the given timezone. */
export function formatDateTime(ms: number, timeZone = "UTC"): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(ms);
}

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
export function formatAgo(ms: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

/** 12345 → "12,345". */
export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export const TIMEFRAME_LABEL: Record<"1d" | "1h" | "15m" | "5m" | "1m", string> = {
  "1d": "Daily",
  "1h": "Hourly",
  "15m": "15 minutes",
  "5m": "5 minutes",
  "1m": "1 minute",
};
