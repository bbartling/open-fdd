import { useMemo } from "react";
import { useSiteContext } from "@/contexts/site-context";
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
import { useAllEquipment, useAllPoints, useEquipment, usePoints, useSites } from "@/hooks/use-sites";
import { useActiveFaults, useSiteFaults } from "@/hooks/use-faults";
import type { Equipment, Point, FaultState, Site } from "@/types/api";

function EquipmentTable({
  equipment,
  points,
  faults,
  siteMap,
}: {
  equipment: Equipment[];
  points: Point[];
  faults: FaultState[];
  siteMap?: Map<string, Site>;
}) {
  if (equipment.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No equipment configured{siteMap ? " across any site" : " for this site"}.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {siteMap && <TableHead>Site</TableHead>}
          <TableHead>Name</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Points</TableHead>
          <TableHead className="text-right">Faults</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {equipment.map((equip) => {
          const pointCount = points.filter((p) => p.equipment_id === equip.id).length;
          const faultCount = faults.filter((f) => f.equipment_id === equip.id).length;

          return (
            <TableRow key={equip.id}>
              {siteMap && (
                <TableCell className="text-muted-foreground">
                  {siteMap.get(equip.site_id)?.name ?? equip.site_id.slice(0, 8)}
                </TableCell>
              )}
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
                {faultCount > 0 ? (
                  <span className="font-medium tabular-nums text-destructive">{faultCount}</span>
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

function AllEquipmentView() {
  const { data: equipment, isLoading } = useAllEquipment();
  const { data: points = [] } = useAllPoints();
  const { data: faults = [] } = useActiveFaults();
  const { data: sites = [] } = useSites();
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <EquipmentTable equipment={equipment ?? []} points={points} faults={faults} siteMap={siteMap} />
  );
}

function SiteEquipmentView({ siteId }: { siteId: string }) {
  const { data: equipment = [], isLoading } = useEquipment(siteId);
  const { data: points = [] } = usePoints(siteId);
  const { data: faults = [] } = useSiteFaults(siteId);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return <EquipmentTable equipment={equipment} points={points} faults={faults} />;
}

export function EquipmentPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Equipment</h1>
      {selectedSiteId ? <SiteEquipmentView siteId={selectedSiteId} /> : <AllEquipmentView />}
    </div>
  );
}
