import { useId, useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { IntervalSeconds, Monitor, MonitorPatch } from "../api/types";
import { useCreateMonitor, useUpdateMonitor } from "../hooks/useMonitors";
import { INTERVAL_OPTIONS } from "../lib/format";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { useToast } from "./Toast";

interface Props {
  open: boolean;
  monitor?: Monitor; // set = edit mode
  onClose: () => void;
}

export function MonitorFormModal({ open, monitor, onClose }: Props) {
  return (
    <Modal open={open} title={monitor ? "Edit monitor" : "Add monitor"} onClose={onClose}>
      <MonitorForm monitor={monitor} onDone={onClose} />
    </Modal>
  );
}

function MonitorForm({ monitor, onDone }: { monitor?: Monitor; onDone: () => void }) {
  const [name, setName] = useState(monitor?.name ?? "");
  const [url, setUrl] = useState(monitor?.url ?? "https://");
  const [interval, setIntervalSeconds] = useState<IntervalSeconds>(monitor?.interval_seconds ?? 60);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const create = useCreateMonitor();
  const update = useUpdateMonitor();
  const toast = useToast();
  const pending = create.isPending || update.isPending;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setErrors({});
    try {
      if (monitor) {
        // Send only what changed: an unchanged URL must not reset the monitor's state.
        const patch: MonitorPatch = {};
        if (name !== monitor.name) patch.name = name;
        if (url !== monitor.url) patch.url = url;
        if (interval !== monitor.interval_seconds) patch.interval_seconds = interval;
        if (Object.keys(patch).length) await update.mutateAsync({ id: monitor.id, patch });
        toast.success(`Saved “${name.trim()}”`);
      } else {
        await create.mutateAsync({ name, url, interval_seconds: interval });
        toast.success(`Added “${name.trim()}”`);
      }
      onDone();
    } catch (error) {
      if (error instanceof ApiError && Object.keys(error.fieldErrors).length) {
        setErrors(error.fieldErrors);
      } else {
        setErrors({ form: error instanceof Error ? error.message : "Something went wrong" });
      }
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {errors.form && <p className="rounded-md bg-red-50 dark:bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">{errors.form}</p>}

      <Field label="Name" error={errors.name}>
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            aria-invalid={!!errors.name}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My website"
            maxLength={100}
            autoFocus
            className={inputClass(!!errors.name)}
          />
        )}
      </Field>

      <Field label="URL" error={errors.url}>
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            aria-invalid={!!errors.url}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            inputMode="url"
            autoComplete="url"
            spellCheck={false}
            placeholder="https://example.com"
            className={inputClass(!!errors.url)}
          />
        )}
      </Field>

      <Field label="Check interval" error={errors.interval_seconds}>
        {(id, describedBy) => (
          <select
            id={id}
            aria-describedby={describedBy}
            value={interval}
            onChange={(e) => setIntervalSeconds(Number(e.target.value) as IntervalSeconds)}
            className={inputClass(!!errors.interval_seconds)}
          >
            {INTERVAL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      </Field>

      <div className="flex justify-end gap-2 pt-2">
        <Button onClick={onDone} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={pending}>
          {pending ? "Saving…" : monitor ? "Save" : "Add monitor"}
        </Button>
      </div>
    </form>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <div className="mt-1">{children(id, error ? errorId : undefined)}</div>
      {error && (
        <p id={errorId} className="mt-1 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

function inputClass(invalid: boolean): string {
  return `block w-full rounded-lg border bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 shadow-sm placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-2 focus:outline-offset-0 ${
    invalid ? "border-red-400 dark:border-red-500 focus:outline-red-500" : "border-slate-300 dark:border-slate-700 focus:outline-slate-900 dark:focus:outline-slate-100"
  }`;
}
