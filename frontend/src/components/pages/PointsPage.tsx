import { useSiteContext } from "@/contexts/site-context";
import { PointsTab } from "@/components/site/PointsTab";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { useAllPoints, useAllEquipment, usePoints, useEquipment } from "@/hooks/use-sites";
import { useSites } from "@/hooks/use-sites";

function AllPointsView() {
  const { data: points, isLoading } = useAllPoints();
  const { data: equipment = [] } = useAllEquipment();
  const { data: sites = [] } = useSites();

  if (isLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  if (!points || points.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No points configured across any site.
        </p>
      </div>
    );
  }

  const equipMap = new Map(equipment.map((e) => [e.id, e]));
  const siteMap = new Map(sites.map((s) => [s.id, s]));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Site</TableHead>
          <TableHead>External ID</TableHead>
          <TableHead>Equipment</TableHead>
          <TableHead>Brick Type</TableHead>
          <TableHead>FDD Input</TableHead>
          <TableHead>Unit</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((point) => {
          const equip = point.equipment_id
            ? equipMap.get(point.equipment_id)
            : undefined;
          const siteName = siteMap.get(point.site_id)?.name ?? point.site_id.slice(0, 8);

          return (
            <TableRow key={point.id}>
              <TableCell className="text-muted-foreground">{siteName}</TableCell>
              <TableCell className="font-mono text-xs">{point.external_id}</TableCell>
              <TableCell>
                {equip?.name ?? (
                  <span className="text-muted-foreground">&mdash;</span>
                )}
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

function SitePointsView({ siteId }: { siteId: string }) {
  const { data: points = [], isLoading } = usePoints(siteId);
  const { data: equipment = [] } = useEquipment(siteId);

  if (isLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  return <PointsTab points={points} equipment={equipment} />;
}

export function PointsPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Points</h1>
      {selectedSiteId ? (
        <SitePointsView siteId={selectedSiteId} />
      ) : (
        <AllPointsView />
      )}
    </div>
  );
}
