import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router";
import { ApiError } from "./api/client";
import { EmptyState } from "./components/States";
import { ThemeToggle } from "./components/ThemeToggle";
import { ToastProvider } from "./components/Toast";
import { Dashboard } from "./pages/Dashboard";
import { MonitorDetail } from "./pages/MonitorDetail";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      // Retry network/server errors once; a 4xx (e.g. 404) won't change on retry.
      retry: (failureCount, error) =>
        failureCount < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      // refetchOnWindowFocus is on by default: coming back to the tab refreshes data.
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <header className="border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
              <Link to="/" className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100">
                <span className="size-2.5 rounded-full bg-emerald-500 ring-4 ring-emerald-100 dark:ring-emerald-900" />
                Uptime Monitor
              </Link>
              <ThemeToggle />
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/monitors/:id" element={<MonitorDetail />} />
              <Route
                path="*"
                element={<EmptyState title="Page not found" description="This page doesn't exist." />}
              />
            </Routes>
          </main>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
