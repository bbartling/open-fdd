import { useCallback } from "react";
import { HealthMatrixSection } from "./HealthMatrixSection";
import { postChillerHealth, postHpHealth } from "../api/analyticsApi";
import {
  postAhuEconomizerHealth,
  postAhuPressureHealth,
  postAhuTemperatureHealth,
  postCoolingTowerHealth,
  postPidHunting,
  postSensorFaults,
} from "../api/overviewHealthApi";

/** MQTT and CSV sites share the same Overview health-matrix chrome (empty shells when no equip). */
export function PlantHealthSections({
  buildingId,
  refreshToken,
}: {
  buildingId: string;
  refreshToken: number;
}) {
  const fetchAhuTemperature = useCallback(
    (id: string) => postAhuTemperatureHealth({ building_id: id }),
    [],
  );
  const fetchAhuPressure = useCallback(
    (id: string) => postAhuPressureHealth({ building_id: id }),
    [],
  );
  const fetchAhuEconomizer = useCallback(
    (id: string) => postAhuEconomizerHealth({ building_id: id }),
    [],
  );
  const fetchChiller = useCallback(
    (id: string) => postChillerHealth({ building_id: id }),
    [],
  );
  const fetchCoolingTower = useCallback(
    (id: string) => postCoolingTowerHealth({ building_id: id }),
    [],
  );
  const fetchHp = useCallback(
    (id: string) => postHpHealth({ building_id: id }),
    [],
  );
  const fetchPid = useCallback(
    (id: string) => postPidHunting({ building_id: id }),
    [],
  );
  const fetchSensors = useCallback(
    (id: string) => postSensorFaults({ building_id: id }),
    [],
  );

  return (
    <>
      <HealthMatrixSection
        family="ahu-temperature"
        title="AHU temperature health"
        caption="Supply and mixed-air temperature diagnostics. Fully faulted rows are highlighted regardless of matrix width."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchAhuTemperature}
        renderEmptyTable
        flagColumns={[
          {
            key: "sat_dev",
            ruleId: "AHU-SATDEV",
            haystackTags: ["dischargeAir", "dischargeAirSp"],
          },
          { key: "mat_low", ruleId: "FC2", haystackTags: ["mixedAir"] },
          { key: "mat_high", ruleId: "FC3", haystackTags: ["mixedAir"] },
          {
            key: "sat_low_heating",
            ruleId: "FC7",
            haystackTags: ["dischargeAir", "heating"],
          },
          {
            key: "sat_high_cooling",
            ruleId: "FC13-SAT-HIGH",
            haystackTags: ["dischargeAir", "cooling"],
          },
        ]}
      />
      <HealthMatrixSection
        family="ahu-pressure"
        title="AHU pressure / fan health"
        caption="Duct static, fan command, and static-pressure reset diagnostics."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchAhuPressure}
        renderEmptyTable
        flagColumns={[
          {
            key: "duct_high",
            ruleId: "AHU-DUCTHI",
            haystackTags: ["ductStatic", "ductStaticSp", "fan"],
          },
          {
            key: "duct_low",
            ruleId: "FC1",
            haystackTags: ["ductStatic", "ductStaticSp"],
          },
          {
            key: "fan_mismatch",
            ruleId: "CMD-1",
            haystackTags: ["fan", "cmd"],
          },
          {
            key: "static_trim",
            ruleId: "TRIM-1",
            haystackTags: ["ductStatic", "ductStaticSp"],
          },
        ]}
      />
      <HealthMatrixSection
        family="ahu-economizer"
        title="AHU economizer health"
        caption="Economizer sequence diagnostics from the canonical ECON rule family."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchAhuEconomizer}
        renderEmptyTable
        flagColumns={[
          {
            key: "stuck_closed",
            ruleId: "ECON-1",
            haystackTags: ["outsideAir", "outsideAirDamper", "fan"],
          },
          {
            key: "unfavorable",
            ruleId: "ECON-2",
            haystackTags: ["outsideAir", "returnAir"],
          },
          {
            key: "mech_without_econ",
            ruleId: "ECON-3",
            haystackTags: ["outsideAir", "cooling"],
          },
          {
            key: "low_oa_fraction",
            ruleId: "ECON-4",
            haystackTags: ["outsideAir", "mixedAir"],
          },
          {
            key: "preheat_over",
            ruleId: "ECON-5",
            haystackTags: ["preheat", "outsideAir"],
          },
          {
            key: "freeze_risk",
            ruleId: "ECON-6",
            haystackTags: ["outsideAir", "mixedAir"],
          },
          {
            key: "not_economizing",
            ruleId: "ECON-7",
            haystackTags: ["outsideAir", "outsideAirDamper"],
          },
        ]}
      />

      <HealthMatrixSection
        family="chiller"
        title="Chiller plant health"
        caption="Expanded chilled-water plant diagnostics. Heat pumps and cooling towers use separate matrices."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchChiller}
        renderEmptyTable
        flagColumns={[
          {
            key: "low_delta_t",
            ruleId: "CHW-1",
            haystackTags: ["chilledWaterSupply", "chilledWaterReturn"],
          },
          {
            key: "dp_low",
            ruleId: "CHW-2",
            haystackTags: ["chilledWaterDiffPressure", "chilledWaterDiffPressureSp"],
          },
          {
            key: "supply_band",
            ruleId: "CHW-3",
            haystackTags: ["chilledWaterSupply", "chilledWaterSupplySp"],
          },
          { key: "flow_high", ruleId: "CHW-4", haystackTags: ["chilledWater", "flow"] },
          { key: "no_load", ruleId: "CHW-NOLOAD-1", haystackTags: ["chilledWater", "load"] },
          {
            key: "chw_reset",
            ruleId: "TRIM-4",
            haystackTags: ["chilledWaterSupply", "chilledWaterSupplySp"],
          },
        ]}
      />

      <HealthMatrixSection
        family="cooling-tower"
        title="Cooling-tower health"
        caption="Condenser-water approach, fan, and optimization diagnostics."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchCoolingTower}
        renderEmptyTable
        flagColumns={[
          {
            key: "approach_high",
            ruleId: "CW-APR-1",
            haystackTags: ["condenserWater", "outsideAirWetBulb"],
          },
          { key: "fan_energy", ruleId: "CW-FAN-1", haystackTags: ["fan", "condenserWater"] },
          {
            key: "cw_optimization",
            ruleId: "CW-OPT-1",
            haystackTags: ["condenserWater", "setpoint"],
          },
        ]}
      />

      <HealthMatrixSection
        family="hp"
        title="Heat-pump health"
        caption="Heat-pump equipment only."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchHp}
        renderEmptyTable
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

      <HealthMatrixSection
        family="pid"
        title="PID Hunting"
        caption="Operating-state and control-output hunting evidence across applicable equipment."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchPid}
        renderEmptyTable
        flagColumns={[
          { key: "operating_state_hunt", ruleId: "FC4" },
          { key: "control_output_hunt", ruleId: "PID-HUNT-1" },
        ]}
      />

      <HealthMatrixSection
        family="sensor"
        title="Sensor faults"
        caption="Sensor validation faults across the current Overview window."
        buildingId={buildingId}
        refreshToken={refreshToken}
        fetchHealth={fetchSensors}
        flagColumns={[
          { key: "flatline", ruleId: "SV-FLATLINE" },
          { key: "range", ruleId: "SV-RANGE" },
          { key: "rate", ruleId: "SV-RATE" },
          { key: "spike", ruleId: "SV-SPIKE" },
          { key: "stale", ruleId: "SV-STALE" },
        ]}
        emptyMessage="No sensor faults in window"
        renderEmptyTable
      />
    </>
  );
}
