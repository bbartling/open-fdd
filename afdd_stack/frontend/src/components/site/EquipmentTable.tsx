import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { Equipment, Point, FaultState, Site } from "@/types/api";

export interface EquipmentTableProps {
  equipment: Equipment[];
  points: Point[];
  faults: FaultState[];
  siteMap?: Map<string, Site>;
}

export function EquipmentTable({
  equipment,
  points,
  faults,
  siteMap,
}: EquipmentTableProps) {
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
