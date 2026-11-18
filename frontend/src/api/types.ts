// Mirrors backend/app/schemas.py. All timestamps are UTC ISO-8601 strings.

export type MonitorStatus = "pending" | "up" | "down";
export type DisplayStatus = "pending" | "up" | "down" | "failing" | "paused";
export type ErrorType =
  | "timeout"
  | "dns"
  | "connection"
  | "ssl"
  | "http_4xx"
  | "http_5xx"
  | "too_many_redirects"
  | "blocked_address"
  | "unknown";

export type IntervalSeconds = 30 | 60 | 300 | 900 | 3600;

export interface Monitor {
  id: number;
  name: string;
  url: string;
  interval_seconds: IntervalSeconds;
  is_paused: boolean;
  status: MonitorStatus;
  display_status: DisplayStatus;
  consecutive_failures: number;
  last_checked_at: string | null;
  last_status_code: number | null;
  last_response_time_ms: number | null;
  last_error_type: ErrorType | null;
  next_check_at: string;
  created_at: string;
  uptime_24h: number | null;
}

export interface Incident {
  id: number;
  started_at: string;
  resolved_at: string | null;
  duration_seconds: number;
  error_type: ErrorType | null;
  error_message: string | null;
}

export interface MonitorStats {
  uptime_24h: number | null;
  uptime_7d: number | null;
  avg_response_ms_24h: number | null;
  open_incident: Incident | null;
}

export interface MonitorDetail extends Monitor {
  stats: MonitorStats;
}

export interface Check {
  id: number;
  checked_at: string;
  is_up: boolean;
  status_code: number | null;
  response_time_ms: number | null;
  error_type: ErrorType | null;
  error_message: string | null;
}

export type ChartRange = "24h" | "7d";

export interface ResponseTimePoint {
  t: string;
  avg_ms: number | null;
  max_ms: number | null;
  checks: number;
  failures: number;
}

export interface ResponseTimes {
  range: ChartRange;
  bucket_seconds: number;
  points: ResponseTimePoint[];
}

export interface MonitorInput {
  name: string;
  url: string;
  interval_seconds: IntervalSeconds;
}

export type MonitorPatch = Partial<MonitorInput> & { is_paused?: boolean };
