import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-slate-900 text-white hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200 shadow-sm",
  secondary: "bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 ring-1 ring-inset ring-slate-300 dark:ring-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50 shadow-sm",
  danger: "bg-red-600 text-white hover:bg-red-500 shadow-sm",
  ghost: "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-100",
};

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 dark:focus-visible:outline-slate-100 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

/**
 * Square icon-only button with an instant tooltip.
 * - `label`: full accessible name for screen readers, e.g. "Pause Google".
 * - `tooltip`: short visible text shown on hover and keyboard focus, e.g. "Pause".
 * The tooltip sits to the LEFT of the button so it stays inside the row and is
 * never clipped by the table's rounded, overflow-hidden container.
 */
export function IconButton({
  label,
  tooltip = label,
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; tooltip?: string; size?: "sm" | "md" }) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={label}
        className={`inline-flex ${size === "sm" ? "size-6" : "size-8"} items-center justify-center rounded-md text-slate-500 dark:text-slate-400 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-slate-900 dark:focus-visible:outline-slate-100 disabled:opacity-50 ${className}`}
        {...props}
      />
      {/* Visual only: the button's aria-label already announces it. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-full z-20 mr-1.5 -translate-y-1/2 rounded-md bg-slate-900 px-2 py-1 text-xs font-medium whitespace-nowrap text-white opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-has-focus-visible:opacity-100 dark:bg-slate-700"
      >
        {tooltip}
      </span>
    </span>
  );
}
