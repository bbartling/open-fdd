import { useSiteContext } from "@/contexts/site-context";
import { EquipmentTab } from "@/components/site/EquipmentTab";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { useAllEquipment, useAllPoints, useEquipment, usePoints } from "@/hooks/use-sites";
import { useActiveFaults, useSiteFaults } from "@/hooks/use-faults";
import { useSites } from "@/hooks/use-sites";

function AllEquipmentView() {
  const { data: equipment, isLoading } = useAllEquipment();
  const { data: points = [] } = useAllPoints();
  const { data: faults = [] } = useActiveFaults();
  const { data: sites = [] } = useSites();

  if (isLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  if (!equipment || equipment.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No equipment configured across any site.
        </p>
      </div>
    );
  }

  const siteMap = new Map(sites.map((s) => [s.id, s]));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Site</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Points</TableHead>
          <TableHead className="text-right">Faults</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {equipment.map((equip) => {
          const pointCount = points.filter(
            (p) => p.equipment_id === equip.id,
          ).length;
          const equipFaults = faults.filter(
            (f) => f.equipment_id === equip.id,
          );
          const siteName = siteMap.get(equip.site_id)?.name ?? equip.site_id.slice(0, 8);

          return (
            <TableRow key={equip.id}>
              <TableCell className="text-muted-foreground">{siteName}</TableCell>
              <TableCell className="font-medium">{equip.name}</TableCell>
              <TableCell>
                {equip.equipment_type ? (
                  <Badge variant="outline">{equip.equipment_type}</Badge>
                ) : (
                  <span className="text-muted-foreground">&mdash;</span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">{pointCount}</TableCell>
              <TableCell className="text-right">
                {equipFaults.length > 0 ? (
                  <span className="font-medium tabular-nums text-destructive">
                    {equipFaults.length}
                  </span>
                ) : (
                  <span className="text-muted-foreground">0</span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function SiteEquipmentView({ siteId }: { siteId: string }) {
  const { data: equipment = [], isLoading: eqLoading } = useEquipment(siteId);
  const { data: points = [] } = usePoints(siteId);
  const { data: faults = [] } = useSiteFaults(siteId);

  if (eqLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  return <EquipmentTab equipment={equipment} points={points} faults={faults} />;
}

export function EquipmentPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Equipment</h1>
      {selectedSiteId ? (
        <SiteEquipmentView siteId={selectedSiteId} />
      ) : (
        <AllEquipmentView />
      )}
    </div>
  );
}
