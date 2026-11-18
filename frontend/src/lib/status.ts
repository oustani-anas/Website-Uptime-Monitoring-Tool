import type { DisplayStatus, Monitor } from "../api/types";

interface StatusMeta {
  label: string;
  dot: string; // dot color
  badge: string; // pill background + text
  rank: number; // dashboard sort order: problems first
}

export const STATUS_META: Record<DisplayStatus, StatusMeta> = {
  down: { label: "Down", dot: "bg-red-500", badge: "bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20 dark:ring-red-500/30", rank: 0 },
  failing: { label: "Unstable", dot: "bg-amber-500", badge: "bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-300 ring-amber-600/20 dark:ring-amber-500/30", rank: 1 },
  up: { label: "Up", dot: "bg-emerald-500", badge: "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20 dark:ring-emerald-500/30", rank: 2 },
  pending: { label: "Checking…", dot: "bg-sky-400", badge: "bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-300 ring-sky-600/20 dark:ring-sky-500/30", rank: 3 },
  paused: { label: "Paused", dot: "bg-slate-400", badge: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 ring-slate-500/20 dark:ring-slate-400/30", rank: 4 },
};

export function sortMonitors(monitors: Monitor[]): Monitor[] {
  return [...monitors].sort(
    (a, b) =>
      STATUS_META[a.display_status].rank - STATUS_META[b.display_status].rank || a.name.localeCompare(b.name),
  );
}
