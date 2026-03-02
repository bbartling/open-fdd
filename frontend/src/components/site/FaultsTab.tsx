import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { timeAgo, severityVariant } from "@/lib/utils";
import type { FaultState, FaultDefinition, Equipment } from "@/types/api";

interface FaultsTabProps {
  faults: FaultState[];
  definitions: FaultDefinition[];
  equipment: Equipment[];
}

export function FaultsTab({ faults, definitions, equipment }: FaultsTabProps) {
  if (faults.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No active faults for this site.
        </p>
      </div>
    );
  }

  const defMap = new Map(definitions.map((d) => [d.fault_id, d]));
  const equipMap = new Map(equipment.map((e) => [e.id, e]));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Equipment</TableHead>
          <TableHead>Fault</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead className="text-right">Since</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {faults.map((fault) => {
          const def = defMap.get(fault.fault_id);
          const equip = equipMap.get(fault.equipment_id);
          const severity = def?.severity ?? "warning";

          return (
            <TableRow key={fault.id}>
              <TableCell className="font-medium">
                {equip?.name ?? fault.equipment_id.slice(0, 8)}
              </TableCell>
              <TableCell>{def?.name ?? fault.fault_id}</TableCell>
              <TableCell>
                <Badge variant={severityVariant(severity)}>{severity}</Badge>
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                {timeAgo(fault.last_changed_ts)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
