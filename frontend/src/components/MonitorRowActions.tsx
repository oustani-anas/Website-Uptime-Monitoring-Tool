import type { Monitor } from "../api/types";
import { IconButton } from "./Button";
import { PauseIcon, PencilIcon, PlayIcon, TrashIcon } from "./Icons";
import type { MonitorActions } from "./useMonitorActions";

/** Pause/resume, edit, delete. Stops click propagation so the row's own click (open detail) doesn't fire. */
export function MonitorRowActions({ monitor, actions }: { monitor: Monitor; actions: MonitorActions }) {
  return (
    <div className="flex items-center justify-end gap-0.5" onClick={(e) => e.stopPropagation()}>
      <IconButton
        label={monitor.is_paused ? `Resume ${monitor.name}` : `Pause ${monitor.name}`}
        onClick={() => actions.togglePause(monitor)}
        disabled={actions.isPausePending(monitor.id)}
      >
        {monitor.is_paused ? <PlayIcon /> : <PauseIcon />}
      </IconButton>
      <IconButton label={`Edit ${monitor.name}`} onClick={() => actions.openEdit(monitor)}>
        <PencilIcon />
      </IconButton>
      <IconButton
        label={`Delete ${monitor.name}`}
        onClick={() => actions.openDelete(monitor)}
        className="hover:bg-red-50 dark:hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
      >
        <TrashIcon />
      </IconButton>
    </div>
  );
}
