import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { FddRunStatus, HealthStatus, Capabilities } from "@/types/api";

export function useFddStatus() {
  return useQuery<FddRunStatus>({
    queryKey: ["fdd-status"],
    queryFn: () => apiFetch<FddRunStatus>("/run-fdd/status"),
    refetchInterval: 60_000,
  });
}

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthStatus>("/health"),
    refetchInterval: 30_000,
  });
}

export function useCapabilities() {
  return useQuery<Capabilities>({
    queryKey: ["capabilities"],
    queryFn: () => apiFetch<Capabilities>("/capabilities"),
    staleTime: 5 * 60 * 1000,
  });
}
