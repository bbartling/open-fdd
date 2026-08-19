import { useCallback, useMemo } from "react";
import { HealthMatrixSection } from "./HealthMatrixSection";
import { postVavHealth } from "../api/analyticsApi";
import type { FddEquipmentItem } from "../api/analyticsApi";
import { plantEquipmentFamilies } from "../lib/plantEquipment";

export function VavHealthSection({
  buildingId,
  refreshToken,
  equipment,
}: {
  buildingId: string;
  refreshToken: number;
  equipment: FddEquipmentItem[];
}) {
  const families = useMemo(() => plantEquipmentFamilies(equipment), [equipment]);
  const fetchHealth = useCallback(
    (id: string) => postVavHealth({ building_id: id }),
    [],
  );

  if (!families.hasVav) return null;

  return (
    <HealthMatrixSection
      family="vav"
      title="VAV zone health"
      caption="Broken-box flags from VAV-3/4/5/7 cookbook rules; comfort and rogue from historian evidence."
      buildingId={buildingId}
      refreshToken={refreshToken}
      fetchHealth={fetchHealth}
      flagColumns={[
        {
          key: "broken_box",
          ruleId: "VAV-3",
          haystackTags: ["reheatValve", "outsideAir", "zoneAirflow"],
          faultHoursKey: "broken_fault_hours",
        },
        {
          key: "poor_zone_performance",
          ruleId: "ZONE-COMFORT",
          haystackTags: ["zoneAir"],
          faultHoursKey: "comfort_fault_h",
        },
        {
          key: "rogue_damper",
          ruleId: "VAV-7",
          haystackTags: ["damper", "zoneAirflow"],
          faultHoursKey: "rogue_fault_h",
        },
      ]}
    />
  );
}
