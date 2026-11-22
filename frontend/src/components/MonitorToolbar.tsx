import type { Monitor } from "../api/types";
import { STATUS_FILTERS, type StatusFilter } from "../lib/filter";
import { STATUS_META } from "../lib/status";
import { SearchIcon, XIcon } from "./Icons";

interface Props {
  monitors: Monitor[]; // all monitors (counts are always over the full list)
  status: StatusFilter;
  query: string;
  onStatusChange: (status: StatusFilter) => void;
  onQueryChange: (query: string) => void;
}

/** Search by name/URL + status filter chips with live counts. */
export function MonitorToolbar({ monitors, status, query, onStatusChange, onQueryChange }: Props) {
  const count = (s: StatusFilter) =>
    s === "all" ? monitors.length : monitors.filter((m) => m.display_status === s).length;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="relative sm:w-72">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
        <input
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search by name or URL"
          aria-label="Search monitors by name or URL"
          className="block w-full rounded-lg border border-slate-300 bg-white py-2 pr-9 pl-9 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:outline-2 focus:outline-offset-0 focus:outline-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:outline-slate-100 [&::-webkit-search-cancel-button]:hidden"
        />
        {query && (
          <button
            type="button"
            onClick={() => onQueryChange("")}
            aria-label="Clear search"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <XIcon className="size-3.5" />
          </button>
        )}
      </div>

      <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((s) => {
          const active = s === status;
          return (
            <button
              key={s}
              type="button"
              aria-pressed={active}
              onClick={() => onStatusChange(s)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ring-1 transition-colors ring-inset focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 dark:focus-visible:outline-slate-100 ${
                active
                  ? "bg-slate-900 text-white ring-slate-900 dark:bg-white dark:text-slate-900 dark:ring-white"
                  : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700 dark:hover:bg-slate-800"
              }`}
            >
              {s !== "all" && <span className={`size-1.5 rounded-full ${STATUS_META[s].dot}`} />}
              {s === "all" ? "All" : STATUS_META[s].label}
              <span className={`tabular-nums ${active ? "opacity-70" : "text-slate-400 dark:text-slate-500"}`}>
                {count(s)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
