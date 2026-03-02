import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { Point, Equipment } from "@/types/api";

interface PointsTabProps {
  points: Point[];
  equipment: Equipment[];
}

export function PointsTab({ points, equipment }: PointsTabProps) {
  if (points.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No points configured for this site.
        </p>
      </div>
    );
  }

  const equipMap = new Map(equipment.map((e) => [e.id, e]));

  return (
    <Table>
      <TableHeader>
        <TableRow>
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

          return (
            <TableRow key={point.id}>
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
