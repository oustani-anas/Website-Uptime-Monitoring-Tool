import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertIcon, CheckIcon } from "./Icons";

type ToastKind = "success" | "error";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}
interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const DISMISS_AFTER_MS = 3000;

/** Small toasts, bottom-right. Announced to screen readers via aria-live. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const show = useCallback((kind: ToastKind, message: string) => {
    const id = ++nextId.current;
    setToasts((current) => [...current, { id, kind, message }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), DISMISS_AFTER_MS);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({ success: (m) => show("success", m), error: (m) => show("error", m) }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] z-50 flex flex-col items-end gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className="flex items-center gap-2 rounded-lg bg-slate-900 px-3.5 py-2.5 text-sm text-white shadow-lg dark:bg-slate-800 dark:ring-1 dark:ring-slate-700"
          >
            {t.kind === "success" ? (
              <CheckIcon className="size-4 text-emerald-400" />
            ) : (
              <AlertIcon className="size-4 text-red-400" />
            )}
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
