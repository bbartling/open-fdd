import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { TimeseriesLatestItem } from "@/types/api";

function buildSearchParams(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== "") sp.set(k, v);
  });
  const q = sp.toString();
  return q ? `?${q}` : "";
}

/**
 * Latest value per point from timeseries_readings (BACnet scraper / weather).
 * Use for Points UI "last value" and "last updated" when polling=true.
 * See docs/modeling/sparql_cookbook.md (Recipe 4, 6) for polling in the data model.
 */
export function useTimeseriesLatest(
  siteId: string | undefined,
  equipmentId?: string | undefined,
) {
  return useQuery<TimeseriesLatestItem[]>({
    queryKey: ["timeseries", "latest", siteId ?? "all", equipmentId ?? "all"],
    queryFn: () =>
      apiFetch<TimeseriesLatestItem[]>(
        `/timeseries/latest${buildSearchParams({
          site_id: siteId ?? undefined,
          equipment_id: equipmentId ?? undefined,
        })}`,
      ),
    enabled: true,
    staleTime: 60 * 1000,
  });
}
