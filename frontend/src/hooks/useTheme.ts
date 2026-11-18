import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const STORAGE_KEY = "theme";
const systemQuery = () => window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage can be blocked (private mode); fall back to the system setting
  }
}

function apply(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

/**
 * Light/dark theme. Default: follow the OS setting (and its live changes).
 * Once the user toggles, that choice is remembered. The initial class is set
 * by an inline script in index.html before first paint (no flash).
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );

  useEffect(() => {
    const query = systemQuery();
    const onChange = () => {
      if (savedTheme()) return; // an explicit choice wins over the OS
      const next: Theme = query.matches ? "dark" : "light";
      apply(next);
      setTheme(next);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      apply(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* not persisted, still applied */
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
