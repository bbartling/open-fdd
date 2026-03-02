import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { FaultState, FaultDefinition } from "@/types/api";

export function useActiveFaults() {
  return useQuery<FaultState[]>({
    queryKey: ["faults", "active"],
    queryFn: () => apiFetch<FaultState[]>("/faults/active"),
  });
}

export function useFaultDefinitions() {
  return useQuery<FaultDefinition[]>({
    queryKey: ["faults", "definitions"],
    queryFn: () => apiFetch<FaultDefinition[]>("/faults/definitions"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSiteFaults(siteId: string | undefined) {
  return useQuery<FaultState[]>({
    queryKey: ["faults", "active", siteId],
    queryFn: () => apiFetch<FaultState[]>(`/faults/active?site_id=${siteId}`),
    enabled: !!siteId,
  });
}
