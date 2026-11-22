import { useSearchParams } from "react-router";
import { Button, IconButton } from "../components/Button";
import { PlusIcon, RefreshIcon } from "../components/Icons";
import { MonitorTable } from "../components/MonitorTable";
import { MonitorToolbar } from "../components/MonitorToolbar";
import { EmptyState, ErrorBanner, TableSkeleton } from "../components/States";
import { SummaryBar } from "../components/SummaryBar";
import { useMonitorActions } from "../components/useMonitorActions";
import { useMonitors } from "../hooks/useMonitors";
import { useNow } from "../hooks/useNow";
import { filterMonitors, parseStatusFilter, type StatusFilter } from "../lib/filter";
import { formatRelative } from "../lib/format";

export function Dashboard() {
  const { data: monitors, error, isPending, isFetching, dataUpdatedAt, refetch } = useMonitors();
  const actions = useMonitorActions();
  const now = useNow();

  // Filters live in the URL (?status=down&q=google): they survive a refresh and can be shared.
  const [searchParams, setSearchParams] = useSearchParams();
  const status = parseStatusFilter(searchParams.get("status"));
  const query = searchParams.get("q") ?? "";
  const visible = monitors ? filterMonitors(monitors, status, query) : [];

  function updateFilters(changes: { status?: StatusFilter; q?: string }) {
    const next = new URLSearchParams(searchParams);
    if (changes.status !== undefined) {
      if (changes.status === "all") next.delete("status");
      else next.set("status", changes.status);
    }
    if (changes.q !== undefined) {
      if (changes.q) next.set("q", changes.q);
      else next.delete("q");
    }
    // replace: typing in the search box shouldn't add a history entry per keystroke
    setSearchParams(next, { replace: true });
  }

  const addButton = (
    <Button variant="primary" onClick={actions.openCreate}>
      <PlusIcon /> Add monitor
    </Button>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Monitors</h1>
          <p className="mt-1 flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400">
            {dataUpdatedAt ? (
              <span className="tabular-nums">Updated {formatRelative(new Date(dataUpdatedAt).toISOString(), now)}</span>
            ) : (
              "Loading…"
            )}
            <IconButton label="Refresh now" tooltip="Refresh" size="sm" onClick={() => refetch()}>
              <RefreshIcon className={`size-3.5 ${isFetching ? "animate-spin" : ""}`} />
            </IconButton>
          </p>
        </div>
        {addButton}
      </div>

      {/* Keep showing the last data if a background refresh fails. */}
      {error && (
        <ErrorBanner
          message={monitors ? `${error.message} Showing the last known data.` : error.message}
          onRetry={() => refetch()}
        />
      )}

      {isPending && !error && <TableSkeleton />}

      {monitors &&
        (monitors.length === 0 ? (
          <EmptyState
            title="No monitors yet"
            description="Add a website URL and it will be checked automatically."
            action={addButton}
          />
        ) : (
          <>
            <SummaryBar monitors={monitors} />
            <MonitorToolbar
              monitors={monitors}
              status={status}
              query={query}
              onStatusChange={(s) => updateFilters({ status: s })}
              onQueryChange={(q) => updateFilters({ q })}
            />
            {visible.length > 0 ? (
              <MonitorTable monitors={visible} actions={actions} />
            ) : (
              <EmptyState
                title="No monitors match"
                description={
                  query ? `Nothing matches “${query.trim()}” with this filter.` : "No monitors have this status right now."
                }
                action={
                  <Button onClick={() => updateFilters({ status: "all", q: "" })}>Clear filters</Button>
                }
              />
            )}
          </>
        ))}

      {actions.dialogs}
    </div>
  );
}
