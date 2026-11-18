import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { ArrowLeftIcon, ExternalLinkIcon } from "../components/Icons";
import { EmptyState, ErrorBanner, TableSkeleton } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { useMonitor } from "../hooks/useMonitors";
import { formatInterval } from "../lib/format";

/**
 * Stage 5: routing + header only. Stage 6 adds the stats, uptime bar, chart,
 * recent checks and incidents.
 */
export function MonitorDetail() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { data: monitor, error, isPending } = useMonitor(id);

  return (
    <div className="space-y-6">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100">
        <ArrowLeftIcon /> All monitors
      </Link>

      {isPending && <TableSkeleton rows={2} />}

      {error && error instanceof ApiError && error.status === 404 ? (
        <EmptyState
          title="Monitor not found"
          description="It may have been deleted."
          action={
            <button className="text-sm font-medium text-slate-900 dark:text-slate-100 underline" onClick={() => navigate("/")}>
              Back to all monitors
            </button>
          }
        />
      ) : (
        error && <ErrorBanner message={error.message} />
      )}

      {monitor && (
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">{monitor.name}</h1>
            <StatusBadge status={monitor.display_status} />
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-slate-500 dark:text-slate-400">
            <a
              href={monitor.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 break-all hover:text-slate-900 dark:hover:text-slate-100 hover:underline"
            >
              {monitor.url} <ExternalLinkIcon className="size-3.5 shrink-0" />
            </a>
            <span>· every {formatInterval(monitor.interval_seconds)}</span>
          </p>
        </div>
      )}
    </div>
  );
}
