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
      title="VAV health — broken boxes, comfort, and rogue zones."
      caption="Three independent dimensions. Missing evidence is unknown, not PASS. One building-scoped request. Full-open prevalence is not an actuator fail flag."
      buildingId={buildingId}
      refreshToken={refreshToken}
      fetchHealth={fetchHealth}
      flagColumns={[
        { key: "broken_box", header: "Broken" },
        { key: "poor_zone_performance", header: "Comfort" },
        { key: "rogue_damper", header: "Rogue" },
      ]}
      extraFilterKey="parent_ahu"
      extraFilterLabel="AHU"
      schemaFallback="vav_health_matrix_v1"
      queryFallback="vav-health-v1"
      csvName="vav_health_matrix.csv"
    />
  );
}
