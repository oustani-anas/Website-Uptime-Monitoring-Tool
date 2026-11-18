import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MonitorInput, MonitorPatch } from "../api/types";

export const DASHBOARD_REFRESH_MS = 10_000;
export const DETAIL_REFRESH_MS = 15_000;

/** Query keys in one place, so invalidation can't drift from the queries. */
export const monitorKeys = {
  all: ["monitors"] as const,
  list: () => [...monitorKeys.all, "list"] as const,
  detail: (id: number) => [...monitorKeys.all, "detail", id] as const,
};

export function useMonitors() {
  return useQuery({
    queryKey: monitorKeys.list(),
    queryFn: api.listMonitors,
    refetchInterval: DASHBOARD_REFRESH_MS,
  });
}

export function useMonitor(id: number) {
  return useQuery({
    queryKey: monitorKeys.detail(id),
    queryFn: () => api.getMonitor(id),
    refetchInterval: DETAIL_REFRESH_MS,
  });
}

// Mutations: after any change, refetch everything under ["monitors"] (list + details).

export function useCreateMonitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: MonitorInput) => api.createMonitor(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: monitorKeys.all }),
  });
}

export function useUpdateMonitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: MonitorPatch }) => api.updateMonitor(id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: monitorKeys.all }),
  });
}

export function useDeleteMonitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteMonitor(id),
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: monitorKeys.detail(id) });
      return queryClient.invalidateQueries({ queryKey: monitorKeys.list() });
    },
  });
}
