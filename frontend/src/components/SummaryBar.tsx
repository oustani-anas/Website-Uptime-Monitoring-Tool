import type { DisplayStatus, Monitor } from "../api/types";
import { STATUS_META } from "../lib/status";

const SHOWN: DisplayStatus[] = ["up", "down", "failing", "paused"];

export function SummaryBar({ monitors }: { monitors: Monitor[] }) {
  const count = (status: DisplayStatus) => monitors.filter((m) => m.display_status === status).length;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <Tile label="Total" value={monitors.length} className="col-span-2 sm:col-span-1" />
      {SHOWN.map((status) => (
        <Tile key={status} label={STATUS_META[status].label} value={count(status)} dot={STATUS_META[status].dot} />
      ))}
    </dl>
  );
}

function Tile({ label, value, dot, className = "" }: { label: string; value: number; dot?: string; className?: string }) {
  return (
    <div className={`rounded-xl bg-white dark:bg-slate-900 px-4 py-3 shadow-sm ring-1 ring-slate-200 dark:ring-slate-800 ${className}`}>
      <dt className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
        {dot && <span className={`size-2 rounded-full ${dot}`} />}
        {label}
      </dt>
      <dd className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100 tabular-nums">{value}</dd>
    </div>
  );
}
