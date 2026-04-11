import { Badge } from "@/components/ui/badge";
import { severityVariant } from "@/lib/utils";
import type { FaultState, FaultDefinition, Equipment } from "@/types/api";

interface FaultRowProps {
  fault: FaultState;
  definition: FaultDefinition | undefined;
  equipment: Equipment | undefined;
}

export function FaultRow({ fault, definition, equipment }: FaultRowProps) {
  const severity = definition?.severity ?? "warning";

  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <div className="min-w-0 truncate">
        <span className="font-medium">
          {equipment?.name ?? fault.equipment_id.slice(0, 8)}
        </span>
        <span className="text-muted-foreground">
          {" "}&mdash; {definition?.name ?? fault.fault_id}
        </span>
      </div>
      <Badge variant={severityVariant(severity)} className="shrink-0">
        {severity}
      </Badge>
    </div>
  );
}
