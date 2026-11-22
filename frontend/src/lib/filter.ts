import type { DisplayStatus, Monitor } from "../api/types";

/** Dashboard filter values. "Checking…" (pending) monitors only appear under "all". */
export type StatusFilter = "all" | Extract<DisplayStatus, "up" | "down" | "failing" | "paused">;

export const STATUS_FILTERS: StatusFilter[] = ["all", "up", "down", "failing", "paused"];

export function parseStatusFilter(value: string | null): StatusFilter {
  return STATUS_FILTERS.includes(value as StatusFilter) ? (value as StatusFilter) : "all";
}

/**
 * Client-side filtering: the dashboard already has every monitor in memory
 * (polled every 10 s), so this is instant and needs no API change.
 */
export function filterMonitors(monitors: Monitor[], status: StatusFilter, query: string): Monitor[] {
  const q = query.trim().toLowerCase();
  return monitors.filter(
    (m) =>
      (status === "all" || m.display_status === status) &&
      (!q || m.name.toLowerCase().includes(q) || m.url.toLowerCase().includes(q)),
  );
}
