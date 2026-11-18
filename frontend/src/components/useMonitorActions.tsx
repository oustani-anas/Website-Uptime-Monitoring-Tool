import { useState } from "react";
import type { Monitor } from "../api/types";
import { useDeleteMonitor, useUpdateMonitor } from "../hooks/useMonitors";
import { ConfirmDialog } from "./ConfirmDialog";
import { MonitorFormModal } from "./MonitorFormModal";
import { useToast } from "./Toast";

type DialogState = { kind: "create" } | { kind: "edit"; monitor: Monitor } | { kind: "delete"; monitor: Monitor } | null;

/**
 * Add / edit / delete / pause logic in one place, shared by the dashboard and
 * the detail page. Returns action functions plus the dialogs to render.
 */
export function useMonitorActions({ onDeleted }: { onDeleted?: () => void } = {}) {
  const [dialog, setDialog] = useState<DialogState>(null);
  const update = useUpdateMonitor();
  const remove = useDeleteMonitor();
  const toast = useToast();
  const close = () => setDialog(null);

  function togglePause(monitor: Monitor) {
    const pausing = !monitor.is_paused;
    update.mutate(
      { id: monitor.id, patch: { is_paused: pausing } },
      {
        onSuccess: () => toast.success(`${pausing ? "Paused" : "Resumed"} “${monitor.name}”`),
        onError: (error) => toast.error(error.message),
      },
    );
  }

  function confirmDelete(monitor: Monitor) {
    remove.mutate(monitor.id, {
      onSuccess: () => {
        toast.success(`Deleted “${monitor.name}”`);
        close();
        onDeleted?.();
      },
      onError: (error) => toast.error(error.message),
    });
  }

  const dialogs = (
    <>
      <MonitorFormModal
        open={dialog?.kind === "create" || dialog?.kind === "edit"}
        monitor={dialog?.kind === "edit" ? dialog.monitor : undefined}
        onClose={close}
      />
      <ConfirmDialog
        open={dialog?.kind === "delete"}
        title="Delete monitor"
        message={
          dialog?.kind === "delete" && (
            <>
              Delete <strong className="text-slate-900 dark:text-slate-100">{dialog.monitor.name}</strong>? Its check history and
              incidents will be removed. This can't be undone.
            </>
          )
        }
        confirmLabel="Delete"
        pending={remove.isPending}
        onConfirm={() => dialog?.kind === "delete" && confirmDelete(dialog.monitor)}
        onClose={close}
      />
    </>
  );

  return {
    openCreate: () => setDialog({ kind: "create" }),
    openEdit: (monitor: Monitor) => setDialog({ kind: "edit", monitor }),
    openDelete: (monitor: Monitor) => setDialog({ kind: "delete", monitor }),
    togglePause,
    isPausePending: (id: number) => update.isPending && update.variables?.id === id,
    dialogs,
  };
}

export type MonitorActions = ReturnType<typeof useMonitorActions>;
