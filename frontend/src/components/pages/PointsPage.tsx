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
import type { Point, Equipment, Site } from "@/types/api";

function PointsTable({
  points,
  equipment,
  siteMap,
}: {
  points: Point[];
  equipment: Equipment[];
  siteMap?: Map<string, Site>;
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
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((point) => {
          const equip = point.equipment_id ? equipMap.get(point.equipment_id) : undefined;

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
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return <PointsTable points={points ?? []} equipment={equipment} siteMap={siteMap} />;
}

function SitePointsView({ siteId }: { siteId: string }) {
  const { data: points = [], isLoading } = usePoints(siteId);
  const { data: equipment = [] } = useEquipment(siteId);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return <PointsTable points={points} equipment={equipment} />;
}

export function PointsPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Points</h1>
      {selectedSiteId ? <SitePointsView siteId={selectedSiteId} /> : <AllPointsView />}
    </div>
  );
}
