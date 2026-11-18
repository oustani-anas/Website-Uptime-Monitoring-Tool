import type { ReactNode } from "react";
import { Button } from "./Button";
import { AlertIcon } from "./Icons";

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="rounded-xl border-2 border-dashed border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6 py-14 text-center">
      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-500/10 px-4 py-3 text-sm text-red-800 dark:text-red-300 ring-1 ring-red-200 dark:ring-red-900">
      <AlertIcon className="size-4 shrink-0" />
      <span className="flex-1">{message}</span>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry} className="text-red-800 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/40">
          Retry
        </Button>
      )}
    </div>
  );
}

export function TableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3 rounded-xl bg-white dark:bg-slate-900 p-4 shadow-sm ring-1 ring-slate-200 dark:ring-slate-800" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-10 animate-pulse rounded-md bg-slate-100 dark:bg-slate-800" />
      ))}
    </div>
  );
}
