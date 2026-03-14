import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type {
  FaultState,
  FaultDefinition,
  FaultSummaryResponse,
  FaultTimeseriesResponse,
  FaultsByEquipmentResponse,
  FaultResultsSeriesResponse,
  FaultResultsRawResponse,
  BacnetDevice,
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

/** Full fault state (active + cleared) for matrix. */
export function useFaultState(siteId: string | undefined) {
  return useQuery<FaultState[]>({
    queryKey: ["faults", "state", siteId ?? "all"],
    queryFn: () =>
      apiFetch<FaultState[]>(
        siteId ? `/faults/state?site_id=${encodeURIComponent(siteId)}` : "/faults/state",
      ),
    staleTime: 30 * 1000,
  });
}

/** BACnet devices from data model (points + equipment). */
export function useBacnetDevices(siteId: string | undefined) {
  return useQuery<BacnetDevice[]>({
    queryKey: ["faults", "bacnet-devices", siteId ?? "all"],
    queryFn: () =>
      apiFetch<BacnetDevice[]>(
        siteId
          ? `/faults/bacnet-devices?site_id=${encodeURIComponent(siteId)}`
          : "/faults/bacnet-devices",
      ),
    staleTime: 60 * 1000,
  });
}

/** YYYY-MM-DD for fault-summary API (backend filters by date). */
function toDateOnly(s: string): string {
  return s.slice(0, 10);
}

export function useFaultSummary(
  siteId: string | undefined,
  startDate: string,
  endDate: string,
) {
  const start = toDateOnly(startDate);
  const end = toDateOnly(endDate);
  return useQuery<FaultSummaryResponse>({
    queryKey: ["faults", "summary", siteId ?? "all", start, end],
    queryFn: () =>
      apiFetch<FaultSummaryResponse>(
        `/analytics/fault-summary${buildSearchParams({
          site_id: siteId ?? undefined,
          start_date: start,
          end_date: end,
        })}`,
      ),
    enabled: !!startDate && !!endDate,
    staleTime: 0,
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

export function useFaultsByEquipment(
  siteId: string | undefined,
  startDate: string,
  endDate: string,
) {
  const start = startDate.slice(0, 10);
  const end = endDate.slice(0, 10);
  return useQuery<FaultsByEquipmentResponse>({
    queryKey: ["faults", "by-equipment", siteId ?? "all", start, end],
    queryFn: () =>
      apiFetch<FaultsByEquipmentResponse>(
        `/analytics/faults-by-equipment${buildSearchParams({
          site_id: siteId ?? undefined,
          start_date: start,
          end_date: end,
        })}`,
      ),
    enabled: !!startDate && !!endDate,
    staleTime: 60 * 1000,
  });
}

/** Distinct fault × site × equipment for data preview selector (tabs/dropdown). */
export function useFaultResultsSeries(
  siteId: string | undefined,
  startDate: string,
  endDate: string,
) {
  const start = startDate.slice(0, 10);
  const end = endDate.slice(0, 10);
  return useQuery<FaultResultsSeriesResponse>({
    queryKey: ["faults", "results-series", siteId ?? "all", start, end],
    queryFn: () =>
      apiFetch<FaultResultsSeriesResponse>(
        `/analytics/fault-results-series${buildSearchParams({
          site_id: siteId ?? undefined,
          start_date: start,
          end_date: end,
        })}`,
      ),
    enabled: !!startDate && !!endDate,
    staleTime: 60 * 1000,
  });
}

/** Last N rows of fault_results for selected series (Excel-style grid). */
export function useFaultResultsRaw(
  faultId: string,
  siteId: string | undefined,
  equipmentId: string | undefined,
  limit: number,
) {
  return useQuery<FaultResultsRawResponse>({
    queryKey: ["faults", "results-raw", faultId, siteId ?? "", equipmentId ?? "", limit],
    queryFn: () => {
      const params = new URLSearchParams({ fault_id: faultId, limit: String(limit) });
      if (siteId) params.set("site_id", siteId);
      if (equipmentId) params.set("equipment_id", equipmentId);
      return apiFetch<FaultResultsRawResponse>(`/analytics/fault-results-raw?${params}`);
    },
    enabled: !!faultId && limit >= 1,
    staleTime: 30 * 1000,
  });
}
