import { Button } from "../components/Button";
import { PlusIcon, RefreshIcon } from "../components/Icons";
import { MonitorTable } from "../components/MonitorTable";
import { EmptyState, ErrorBanner, TableSkeleton } from "../components/States";
import { SummaryBar } from "../components/SummaryBar";
import { useMonitorActions } from "../components/useMonitorActions";
import { useMonitors } from "../hooks/useMonitors";
import { useNow } from "../hooks/useNow";
import { formatRelative } from "../lib/format";

export function Dashboard() {
  const { data: monitors, error, isPending, isFetching, dataUpdatedAt, refetch } = useMonitors();
  const actions = useMonitorActions();
  const now = useNow();

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
            <button
              type="button"
              onClick={() => refetch()}
              aria-label="Refresh now"
              title="Refresh now"
              className="rounded p-1 hover:bg-slate-200 dark:hover:bg-slate-700 hover:text-slate-900 dark:hover:text-slate-100"
            >
              <RefreshIcon className={`size-3.5 ${isFetching ? "animate-spin" : ""}`} />
            </button>
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
            <MonitorTable monitors={monitors} actions={actions} />
          </>
        ))}

      {actions.dialogs}
    </div>
  );
}
