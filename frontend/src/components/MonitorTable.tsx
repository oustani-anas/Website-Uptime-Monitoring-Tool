import { Link, useNavigate } from "react-router";
import type { Monitor } from "../api/types";
import { useNow } from "../hooks/useNow";
import {
  displayUrl,
  formatErrorType,
  formatInterval,
  formatMs,
  formatPercent,
  formatRelative,
  responseTimeTone,
} from "../lib/format";
import { sortMonitors } from "../lib/status";
import { MonitorRowActions } from "./MonitorRowActions";
import { StatusBadge } from "./StatusBadge";
import type { MonitorActions } from "./useMonitorActions";

interface Props {
  monitors: Monitor[];
  actions: MonitorActions;
}

/** Table on desktop, stacked cards on phones. Problems (down, unstable) sort to the top. */
export function MonitorTable({ monitors, actions }: Props) {
  const now = useNow();
  const navigate = useNavigate();
  const sorted = sortMonitors(monitors);

  return (
    <div className="overflow-hidden rounded-xl bg-white dark:bg-slate-900 shadow-sm ring-1 ring-slate-200 dark:ring-slate-800">
      {/* Desktop */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 text-left text-xs font-medium tracking-wide text-slate-500 dark:text-slate-400 uppercase">
            <tr>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Monitor</th>
              <th className="px-4 py-3 text-right">Response</th>
              <th className="px-4 py-3 text-right">Uptime 24h</th>
              <th className="px-4 py-3">Last check</th>
              <th className="px-4 py-3">Interval</th>
              <th className="px-4 py-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {sorted.map((m) => (
              <tr
                key={m.id}
                onClick={() => navigate(`/monitors/${m.id}`)}
                className="cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/50"
              >
                <td className="px-4 py-3">
                  <StatusBadge status={m.display_status} />
                </td>
                <td className="max-w-xs px-4 py-3">
                  <NameCell monitor={m} />
                </td>
                <td className="px-4 py-3 text-right">
                  <ResponseCell monitor={m} />
                </td>
                <td className={`px-4 py-3 text-right tabular-nums ${m.uptime_24h == null ? "text-slate-400 dark:text-slate-500" : "text-slate-700 dark:text-slate-300"}`}>
                  {formatPercent(m.uptime_24h)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400 tabular-nums" title={m.last_checked_at ?? ""}>
                  {formatRelative(m.last_checked_at, now)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">{formatInterval(m.interval_seconds)}</td>
                <td className="px-2 py-3">
                  <MonitorRowActions monitor={m} actions={actions} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile */}
      <ul className="divide-y divide-slate-100 dark:divide-slate-800 md:hidden">
        {sorted.map((m) => (
          <li key={m.id} onClick={() => navigate(`/monitors/${m.id}`)} className="cursor-pointer px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <NameCell monitor={m} />
              </div>
              <StatusBadge status={m.display_status} />
            </div>
            <div className="mt-2 flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
              {m.last_checked_at ? (
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  <ResponseCell monitor={m} />
                  <span className="tabular-nums">{formatPercent(m.uptime_24h)} 24h</span>
                  <span className="tabular-nums">{formatRelative(m.last_checked_at, now)}</span>
                </div>
              ) : (
                <span>No checks yet</span>
              )}
              <MonitorRowActions monitor={m} actions={actions} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NameCell({ monitor }: { monitor: Monitor }) {
  return (
    <>
      <Link
        to={`/monitors/${monitor.id}`}
        onClick={(e) => e.stopPropagation()}
        className="block truncate font-medium text-slate-900 dark:text-slate-100 hover:underline"
      >
        {monitor.name}
      </Link>
      <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{displayUrl(monitor.url)}</span>
    </>
  );
}

/** Response time when the last check got a response, otherwise the error. */
function ResponseCell({ monitor }: { monitor: Monitor }) {
  if (monitor.last_error_type && monitor.last_response_time_ms == null) {
    return <span className="text-xs font-medium whitespace-nowrap text-red-600 dark:text-red-400">{formatErrorType(monitor.last_error_type)}</span>;
  }
  return (
    // A failed check (e.g. HTTP 503) is red regardless of how fast the error page came back.
    <span
      className={`whitespace-nowrap tabular-nums ${
        monitor.last_error_type ? "text-red-600 dark:text-red-400" : responseTimeTone(monitor.last_response_time_ms)
      }`}
    >
      {formatMs(monitor.last_response_time_ms)}
      {monitor.last_error_type && <span className="ml-1 text-xs">({monitor.last_status_code})</span>}
    </span>
  );
}
