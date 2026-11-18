import type { DisplayStatus } from "../api/types";
import { STATUS_META } from "../lib/status";

/** Colored dot + text label: status is never conveyed by color alone. */
export function StatusBadge({ status }: { status: DisplayStatus }) {
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap ${meta.badge}`}
    >
      <span className={`size-1.5 rounded-full ${meta.dot} ${status === "down" ? "animate-pulse" : ""}`} />
      {meta.label}
    </span>
  );
}
