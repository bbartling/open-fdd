import { useCallback } from "react";
import { HealthMatrixSection } from "./HealthMatrixSection";
import { postVavHealth } from "../api/analyticsApi";

export function VavHealthSection({
  buildingId,
  refreshToken,
}: {
  buildingId: string;
  refreshToken: number;
}) {
  const fetchHealth = useCallback(
    (id: string) => postVavHealth({ building_id: id }),
    [],
  );

  return (
    <HealthMatrixSection
      family="vav"
      title="VAV zone health"
      caption="Broken-box flags from VAV-3/4/5/7 cookbook rules; comfort and rogue from historian evidence."
      buildingId={buildingId}
      refreshToken={refreshToken}
      fetchHealth={fetchHealth}
      renderEmptyTable
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
