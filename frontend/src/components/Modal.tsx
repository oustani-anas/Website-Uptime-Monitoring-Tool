import { useEffect, useId, useRef, type ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * Built on the native <dialog> element: focus trapping, Esc-to-close and the
 * backdrop come from the browser. Children mount only while open, so forms
 * inside start fresh every time.
 */
export function Modal({ open, title, onClose, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      // A click whose target is the <dialog> itself landed on the backdrop.
      onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl bg-white dark:bg-slate-900 p-0 shadow-xl backdrop:bg-slate-900/40 dark:ring-1 dark:ring-slate-700 dark:backdrop:bg-black/70"
    >
      {open && (
        <div className="p-6">
          <h2 id={titleId} className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {title}
          </h2>
          <div className="mt-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}
