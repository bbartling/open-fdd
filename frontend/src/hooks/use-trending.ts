import { useQuery } from "@tanstack/react-query";
import { fetchCsv, parseLongCsv, pivotForChart } from "@/lib/csv";
import type { PivotRow } from "@/lib/csv";

export function useTrendingData(
  siteId: string | undefined,
  pointIds: string[],
  startDate: string,
  endDate: string,
) {
  return useQuery<PivotRow[]>({
    queryKey: ["trending", siteId, pointIds, startDate, endDate],
    queryFn: async () => {
      try {
        const csv = await fetchCsv({
          site_id: siteId!,
          point_ids: pointIds,
          start_date: startDate.slice(0, 10),
          end_date: endDate.slice(0, 10),
          format: "long",
        });
        const rows = parseLongCsv(csv);
        return pivotForChart(rows);
      } catch (e) {
        // API returns 404 when there's no data — treat as empty, not error
        if (e instanceof Error && e.message.includes("404")) return [];
        throw e;
      }
    },
    enabled: !!siteId && pointIds.length > 0,
    staleTime: 2 * 60 * 1000,
  });
}
