import type { ErrorType, IntervalSeconds } from "../api/types";

export const DASH = "—";

export const INTERVAL_OPTIONS: { value: IntervalSeconds; label: string }[] = [
  { value: 30, label: "Every 30 seconds" },
  { value: 60, label: "Every 1 minute" },
  { value: 300, label: "Every 5 minutes" },
  { value: 900, label: "Every 15 minutes" },
  { value: 3600, label: "Every hour" },
];

export function formatInterval(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${seconds / 60} min`;
  return `${seconds / 3600} h`;
}

export function formatMs(ms: number | null | undefined): string {
  return ms == null ? DASH : `${ms.toLocaleString()} ms`;
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? DASH : `${value.toFixed(2)}%`;
}

/** "just now", "12s ago", "5m ago", "3h ago", "2d ago". */
export function formatRelative(iso: string | null | undefined, now: number): string {
  if (!iso) return DASH;
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** "45s", "26m", "1h 4m", "2d 3h". */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return h ? `${d}d ${h}h` : `${d}d`;
  if (h) return m ? `${h}h ${m}m` : `${h}h`;
  if (m) return `${m}m`;
  return `${s}s`;
}

/** Local date + time, e.g. "Nov 18, 17:25:33". */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const ERROR_LABELS: Record<ErrorType, string> = {
  timeout: "Timeout",
  dns: "DNS error",
  connection: "Connection error",
  ssl: "SSL error",
  http_4xx: "HTTP 4xx",
  http_5xx: "HTTP 5xx",
  too_many_redirects: "Too many redirects",
  blocked_address: "Blocked address",
  unknown: "Unknown error",
};

export function formatErrorType(type: ErrorType | null | undefined): string {
  return type ? ERROR_LABELS[type] : DASH;
}

/** Color hint for a response time: fast / ok / slow. */
export function responseTimeTone(ms: number | null | undefined): string {
  if (ms == null) return "text-slate-400 dark:text-slate-500";
  if (ms < 500) return "text-emerald-700 dark:text-emerald-400";
  if (ms < 1500) return "text-amber-700 dark:text-amber-400";
  return "text-red-700 dark:text-red-400";
}

/** Strip the scheme for compact display: "https://example.com/x" -> "example.com/x". */
export function displayUrl(url: string): string {
  return url.replace(/^https?:\/\//, "");
}
