import { useMemo } from "react";
import { useSiteContext } from "@/contexts/site-context";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { useAllPoints, useAllEquipment, usePoints, useEquipment, useSites } from "@/hooks/use-sites";
import { useTimeseriesLatest } from "@/hooks/use-timeseries-latest";
import type { Point, Equipment, Site } from "@/types/api";
import { Circle, CircleDot } from "lucide-react";

/** Format ts for display; full ISO in title for accessibility. */
function formatLastUpdated(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffM = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMs / 3600000);
  const diffD = Math.floor(diffMs / 86400000);
  if (diffM < 1) return "just now";
  if (diffM < 60) return `${diffM}m ago`;
  if (diffH < 24) return `${diffH}h ago`;
  if (diffD < 7) return `${diffD}d ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function PointsTable({
  points,
  equipment,
  siteMap,
  latestByPointId,
}: {
  points: Point[];
  equipment: Equipment[];
  siteMap?: Map<string, Site>;
  /** Latest value/ts per point_id from GET /timeseries/latest (for polled points). */
  latestByPointId?: Map<string, { value: number; ts: string | null }>;
}) {
  const equipMap = useMemo(() => new Map(equipment.map((e) => [e.id, e])), [equipment]);

  if (points.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No points configured{siteMap ? " across any site" : " for this site"}.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {siteMap && <TableHead>Site</TableHead>}
          <TableHead>External ID</TableHead>
          <TableHead>Equipment</TableHead>
          <TableHead>Brick Type</TableHead>
          <TableHead>FDD Input</TableHead>
          <TableHead>Unit</TableHead>
          <TableHead className="w-[90px]">Polling</TableHead>
          <TableHead className="min-w-[100px]">Last value</TableHead>
          <TableHead className="w-[120px]">Last updated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((point) => {
          const equip = point.equipment_id ? equipMap.get(point.equipment_id) : undefined;
          const latest = latestByPointId?.get(point.id);

          return (
            <TableRow key={point.id}>
              {siteMap && (
                <TableCell className="text-muted-foreground">
                  {siteMap.get(point.site_id)?.name ?? point.site_id.slice(0, 8)}
                </TableCell>
              )}
              <TableCell className="font-mono text-xs">{point.external_id}</TableCell>
              <TableCell>
                {equip?.name ?? <span className="text-muted-foreground">&mdash;</span>}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {point.brick_type ?? <span>&mdash;</span>}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {point.fdd_input ?? <span>&mdash;</span>}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {point.unit ?? <span>&mdash;</span>}
              </TableCell>
              <TableCell>
                {point.polling ? (
                  <span title="BACnet scraper polls this point" aria-label="Polled by BACnet scraper">
                    <CircleDot className="h-4 w-4 text-primary" />
                  </span>
                ) : (
                  <span title="Not polled by BACnet scraper" aria-label="Not polled">
                    <Circle className="h-4 w-4 text-muted-foreground" />
                  </span>
                )}
              </TableCell>
              <TableCell className="tabular-nums text-muted-foreground">
                {point.polling && latest != null ? (
                  <span
                    title={latest.ts ? new Date(latest.ts).toLocaleString() : undefined}
                  >
                    {latest.value.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                    {point.unit ? ` ${point.unit}` : ""}
                  </span>
                ) : (
                  <span className="text-muted-foreground/70">—</span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground text-xs">
                {point.polling && latest != null && latest.ts ? (
                  <span title={new Date(latest.ts).toLocaleString()}>
                    {formatLastUpdated(latest.ts)}
                  </span>
                ) : (
                  "—"
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function AllPointsView() {
  const { data: points, isLoading } = useAllPoints();
  const { data: equipment = [] } = useAllEquipment();
  const { data: sites = [] } = useSites();
  const { data: latestList = [] } = useTimeseriesLatest(undefined);
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);
  const latestByPointId = useMemo(
    () =>
      new Map(
        latestList.map((r) => [r.point_id, { value: r.value, ts: r.ts }]),
      ),
    [latestList],
  );

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <PointsTable
      points={points ?? []}
      equipment={equipment}
      siteMap={siteMap}
      latestByPointId={latestByPointId}
    />
  );
}

function SitePointsView({ siteId }: { siteId: string }) {
  const { data: points = [], isLoading } = usePoints(siteId);
  const { data: equipment = [] } = useEquipment(siteId);
  const { data: latestList = [] } = useTimeseriesLatest(siteId);
  const latestByPointId = useMemo(
    () =>
      new Map(
        latestList.map((r) => [r.point_id, { value: r.value, ts: r.ts }]),
      ),
    [latestList],
  );

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <PointsTable
      points={points}
      equipment={equipment}
      latestByPointId={latestByPointId}
    />
  );
}

export function PointsPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">Points</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Polling (data model) indicates whether the BACnet scraper polls this point; last value and time come from
        timeseries. See{" "}
        <a
          href="https://github.com/open-fdd/open-fdd/blob/main/docs/modeling/sparql_cookbook.md"
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:text-foreground"
        >
          SPARQL cookbook
        </a>{" "}
        (Recipe 4 & 6) for polling in the graph.
      </p>
      {selectedSiteId ? <SitePointsView siteId={selectedSiteId} /> : <AllPointsView />}
    </div>
  );
}
