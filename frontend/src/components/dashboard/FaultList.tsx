import { Separator } from "@/components/ui/separator";
import { FaultRow } from "./FaultRow";
import type { FaultState, FaultDefinition, Equipment } from "@/types/api";

const MAX_VISIBLE = 5;

interface FaultListProps {
  faults: FaultState[];
  definitions: FaultDefinition[];
  equipment: Equipment[];
}

export function FaultList({ faults, definitions, equipment }: FaultListProps) {
  if (faults.length === 0) return null;

  const defMap = new Map(definitions.map((d) => [d.fault_id, d]));
  const equipMap = new Map(equipment.map((e) => [e.id, e]));
  const visible = faults.slice(0, MAX_VISIBLE);
  const remaining = faults.length - MAX_VISIBLE;

  return (
    <div>
      <Separator className="my-3" />
      <div className="space-y-2">
        {visible.map((f) => (
          <FaultRow
            key={f.id}
            fault={f}
            definition={defMap.get(f.fault_id)}
            equipment={equipMap.get(f.equipment_id)}
          />
        ))}
        {remaining > 0 && (
          <p className="text-xs text-muted-foreground">
            +{remaining} more&hellip;
          </p>
        )}
      </div>
    </div>
  );
}
