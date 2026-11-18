import type { ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({ open, title, message, confirmLabel, pending, onConfirm, onClose }: ConfirmDialogProps) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <p className="text-sm text-slate-600 dark:text-slate-400">{message}</p>
      <div className="mt-6 flex justify-end gap-2">
        <Button onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        <Button variant="danger" onClick={onConfirm} disabled={pending} autoFocus>
          {pending ? "Deleting…" : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
