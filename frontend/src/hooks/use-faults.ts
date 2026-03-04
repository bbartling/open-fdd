import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type {
  FaultState,
  FaultDefinition,
  FaultSummaryResponse,
  FaultTimeseriesResponse,
} from "@/types/api";

function buildSearchParams(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== "") sp.set(k, v);
  });
  const q = sp.toString();
  return q ? `?${q}` : "";
}

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

export function useFaultSummary(
  siteId: string | undefined,
  startDate: string,
  endDate: string,
) {
  return useQuery<FaultSummaryResponse>({
    queryKey: ["faults", "summary", siteId ?? "all", startDate, endDate],
    queryFn: () =>
      apiFetch<FaultSummaryResponse>(
        `/analytics/fault-summary${buildSearchParams({
          site_id: siteId ?? undefined,
          start_date: startDate.slice(0, 10),
          end_date: endDate.slice(0, 10),
        })}`,
      ),
    enabled: !!startDate && !!endDate,
    staleTime: 60 * 1000,
  });
}

export function useFaultTimeseries(
  siteId: string | undefined,
  startDate: string,
  endDate: string,
  bucket: "hour" | "day" = "hour",
) {
  return useQuery<FaultTimeseriesResponse>({
    queryKey: ["faults", "timeseries", siteId ?? "all", startDate, endDate, bucket],
    queryFn: () =>
      apiFetch<FaultTimeseriesResponse>(
        `/analytics/fault-timeseries${buildSearchParams({
          site_id: siteId ?? undefined,
          start_date: startDate.slice(0, 10),
          end_date: endDate.slice(0, 10),
          bucket,
        })}`,
      ),
    enabled: !!startDate && !!endDate,
    staleTime: 60 * 1000,
  });
}
