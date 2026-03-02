import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { Equipment, Point, FaultState } from "@/types/api";

interface EquipmentTabProps {
  equipment: Equipment[];
  points: Point[];
  faults: FaultState[];
}

export function EquipmentTab({ equipment, points, faults }: EquipmentTabProps) {
  if (equipment.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No equipment configured for this site.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
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
          const hasFaults = equipFaults.length > 0;

          return (
            <TableRow key={equip.id}>
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
                {hasFaults ? (
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
