/** Shared query hooks. One place decides how often each surface refetches. */
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { api, type AppSettings, type Connection, type Status, type SyncRun } from "./api";

export const REFRESH_FAST = 30_000;
export const REFRESH_SLOW = 120_000;

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => api.get<Status>("/status"),
    refetchInterval: REFRESH_FAST,
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<AppSettings>("/settings") });
}

export function useConnections() {
  return useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<Connection[]>("/connections"),
    refetchInterval: REFRESH_SLOW,
  });
}

/** Polls faster while a run is in flight, then falls back to the slow cadence. */
export function useLatestSync() {
  return useQuery({
    queryKey: ["sync", "latest"],
    queryFn: () => api.get<SyncRun | null>("/sync/latest"),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3_000 : REFRESH_SLOW,
  });
}

export function useStartSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post("/sync", body),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["sync"] });
      // Give the run a moment to write its first rows before refreshing views.
      setTimeout(() => client.invalidateQueries(), 4_000);
    },
  });
}

/** The unit system the user chose, defaulting to metric until settings load. */
export function useUnits(): "metric" | "imperial" {
  const { data } = useSettings();
  return data?.unit_system === "imperial" ? "imperial" : "metric";
}

export function useTimezone(): string {
  const { data } = useSettings();
  return data?.timezone ?? "Europe/Oslo";
}
