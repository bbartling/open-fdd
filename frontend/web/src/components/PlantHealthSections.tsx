import { useCallback, useMemo } from "react";
import { HealthMatrixSection } from "./HealthMatrixSection";
import {
  postAhuHealth,
  postChillerHealth,
  postHpHealth,
} from "../api/analyticsApi";
import type { FddEquipmentItem } from "../api/analyticsApi";
import { plantEquipmentFamilies } from "../lib/plantEquipment";

export function PlantHealthSections({
  buildingId,
  refreshToken,
  equipment,
}: {
  buildingId: string;
  refreshToken: number;
  equipment: FddEquipmentItem[];
}) {
  const families = useMemo(() => plantEquipmentFamilies(equipment), [equipment]);

  const fetchAhu = useCallback(
    (id: string) => postAhuHealth({ building_id: id }),
    [],
  );
  const fetchChiller = useCallback(
    (id: string) => postChillerHealth({ building_id: id }),
    [],
  );
  const fetchHp = useCallback(
    (id: string) => postHpHealth({ building_id: id }),
    [],
  );

  return (
    <>
      {families.hasAhu ? (
        <HealthMatrixSection
          family="ahu"
          title="AHU health"
          caption="Data-model scoped to AHU equip refs. Red = all cookbook flags faulted (3/3)."
          buildingId={buildingId}
          refreshToken={refreshToken}
          fetchHealth={fetchAhu}
          flagColumns={[
            {
              key: "sat_dev",
              ruleId: "AHU-SATDEV",
              haystackTags: ["dischargeAir", "dischargeAirSp"],
            },
            {
              key: "duct_high",
              ruleId: "AHU-DUCTHI",
              haystackTags: ["ductStatic", "ductStaticSp", "fan"],
            },
            {
              key: "economizer",
              ruleId: "ECON-1",
              haystackTags: ["outsideAir", "outsideAirDamper", "fan"],
            },
          ]}
        />
      ) : null}
      {families.hasChiller ? (
        <HealthMatrixSection
          family="chiller"
          title="Chiller plant health"
          caption="Compressor-plant flags only. Heat pumps (HP_*) use the heat-pump matrix."
          buildingId={buildingId}
          refreshToken={refreshToken}
          fetchHealth={fetchChiller}
          flagColumns={[
            {
              key: "chw_1",
              ruleId: "CHW-1",
              haystackTags: ["chilledWaterSupply", "chilledWaterReturn"],
            },
            {
              key: "chw_2",
              ruleId: "CHW-2",
              haystackTags: ["chilledWaterDiffPressure", "chilledWaterDiffPressureSp"],
            },
            {
              key: "chw_3",
              ruleId: "CHW-3",
              haystackTags: ["condenserWaterSupply", "condenserWaterReturn"],
            },
          ]}
        />
      ) : null}
      {families.hasHeatPump ? (
        <HealthMatrixSection
          family="hp"
          title="Heat-pump health"
          caption="HP_* equip refs only."
          buildingId={buildingId}
          refreshToken={refreshToken}
          fetchHealth={fetchHp}
          flagColumns={[
            {
              key: "hp_1",
              ruleId: "HP-1",
              haystackTags: ["dischargeAir", "zoneAir", "fan"],
            },
            {
              key: "sat_dev",
              ruleId: "AHU-SATDEV",
              haystackTags: ["dischargeAir", "dischargeAirSp"],
            },
            {
              key: "economizer",
              ruleId: "ECON-1",
              haystackTags: ["outsideAir", "outsideAirDamper", "fan"],
            },
          ]}
        />
      ) : null}
    </>
  );
}
