import { useCallback } from "react";
import { HealthMatrixSection } from "./HealthMatrixSection";
import {
  postAhuHealth,
  postBoilerHealth,
  postChillerHealth,
  postHpHealth,
} from "../api/analyticsApi";

export function PlantHealthSections({
  buildingId,
  refreshToken,
}: {
  buildingId: string;
  refreshToken: number;
}) {
  const fetchAhu = useCallback(
    (id: string) => postAhuHealth({ building_id: id }),
    [],
  );
  const fetchChiller = useCallback(
    (id: string) => postChillerHealth({ building_id: id }),
    [],
  );
  const fetchBoiler = useCallback(
    (id: string) => postBoilerHealth({ building_id: id }),
    [],
  );
  const fetchHp = useCallback(
    (id: string) => postHpHealth({ building_id: id }),
    [],
  );
  return (
    <>
      <HealthMatrixSection
        family="ahu"
        title="AHU health — SAT, duct static, economizer."
        caption="AHU-SATDEV / AHU-DUCTHI / ECON-1 (ECON-2 if ECON-1 is not applicable). Missing evidence is unknown, not PASS."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchAhu}
        flagColumns={[
          { key: "sat_dev", header: "SAT" },
          { key: "duct_high", header: "Duct" },
          { key: "economizer", header: "Econ" },
        ]}
        schemaFallback="ahu_health_matrix_v1"
        queryFallback="ahu-health-v1"
        csvName="ahu_health_matrix.csv"
      />
      <HealthMatrixSection
        family="chiller"
        title="Chiller health — CHW-1 / CHW-2 / CHW-3."
        caption="Compressor-plant flags only. Heat pumps (HP_*) are in the heat-pump matrix. Missing evidence is unknown, not PASS."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchChiller}
        flagColumns={[
          { key: "chw_1", header: "CHW-1" },
          { key: "chw_2", header: "CHW-2" },
          { key: "chw_3", header: "CHW-3" },
        ]}
        schemaFallback="chiller_health_matrix_v1"
        queryFallback="chiller-health-v1"
        csvName="chiller_health_matrix.csv"
      />
      <HealthMatrixSection
        family="boiler"
        title="Boiler health — FC5 / FC6 / FC8."
        caption="Heating cookbook flags until HW-* SQL exists. Units with zero applicable flags score ?/3 (no red)."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchBoiler}
        flagColumns={[
          { key: "fc5", header: "FC5" },
          { key: "fc6", header: "FC6" },
          { key: "fc8", header: "FC8" },
        ]}
        schemaFallback="boiler_health_matrix_v1"
        queryFallback="boiler-health-v1"
        csvName="boiler_health_matrix.csv"
      />
      <HealthMatrixSection
        family="hp"
        title="Heat-pump health — HP-1, SAT, economizer."
        caption="HP-1 plus AHU-SATDEV / ECON-1 for HP_* equipment. Missing evidence is unknown, not PASS."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchHp}
        flagColumns={[
          { key: "hp_1", header: "HP-1" },
          { key: "sat_dev", header: "SAT" },
          { key: "economizer", header: "Econ" },
        ]}
        schemaFallback="hp_health_matrix_v1"
        queryFallback="hp-health-v1"
        csvName="hp_health_matrix.csv"
      />
    </>
  );
}
