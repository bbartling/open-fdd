/** Frozen vibe19 dashboard sections — mirror app/dashboard_contract.py */

export const VIBE19_SECTIONS = [
  "Overview",
  "Data Model",
  "Run Rules",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
  "Energy Model",
  "Export",
] as const;

export type Vibe19Section = (typeof VIBE19_SECTIONS)[number];

/** Chart APIs required for Plotly parity with vibe19. */
export const REQUIRED_CHART_APIS = [
  "rule_result_chart",
  "multi_equipment_timeseries",
  "multi_equipment_box",
  "oat_scatter",
  "motor_weekly_runtime_chart",
  "mech_cooling_oat_histogram",
  "bas_vs_web_oat_histogram",
  "bas_vs_web_oat_overlay",
  "equipment_inspection_chart",
  "sensor_fault_chart",
  "vav_comfort_donut",
  "metering_bar_scatter",
] as const;

/**
 * Frozen RCx preset ids from vibe19 `REQUIRED_RCX_PRESET_IDS`.
 * Weather policy: dry-bulb (web OAT) for SAT/HW/CHW resets; wet-bulb for CW/tower.
 */
export const REQUIRED_RCX_PRESET_IDS = [
  "zone_comfort_rank",
  "zone_temps",
  "ahu_dats",
  "ahu_mats",
  "ahu_rats",
  "ahu_dampers",
  "duct_static_box",
  "ahu_sat_reset_scatter",
  "hw_reset_scatter",
  "chw_reset_scatter",
  "cw_reset_scatter",
  "vav_flows",
  "fan_speeds",
  "meter_elec_cdd",
  "meter_gas_hdd",
] as const;

export type RcxPresetId = (typeof REQUIRED_RCX_PRESET_IDS)[number];

export type RcxWeatherAxis = "dry_bulb" | "wet_bulb" | "none";

export type RcxPresetMeta = {
  id: RcxPresetId;
  label: string;
  family: string;
  chart: "timeseries" | "box" | "scatter" | "donut" | "metering";
  weatherAxis: RcxWeatherAxis;
};

export const RCX_PRESETS: RcxPresetMeta[] = [
  {
    id: "zone_comfort_rank",
    label: "Zone comfort rank",
    family: "Zone",
    chart: "donut",
    weatherAxis: "none",
  },
  {
    id: "zone_temps",
    label: "Zone temperatures",
    family: "Zone",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "ahu_dats",
    label: "AHU discharge air temps",
    family: "AHU",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "ahu_mats",
    label: "AHU mixed air temps",
    family: "AHU",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "ahu_rats",
    label: "AHU return air temps",
    family: "AHU",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "ahu_dampers",
    label: "AHU OA dampers",
    family: "AHU",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "duct_static_box",
    label: "Duct static (fan-on box)",
    family: "AHU",
    chart: "box",
    weatherAxis: "none",
  },
  {
    id: "ahu_sat_reset_scatter",
    label: "AHU SAT reset vs web dry-bulb",
    family: "AHU",
    chart: "scatter",
    weatherAxis: "dry_bulb",
  },
  {
    id: "hw_reset_scatter",
    label: "HW leave reset vs web dry-bulb",
    family: "Plant",
    chart: "scatter",
    weatherAxis: "dry_bulb",
  },
  {
    id: "chw_reset_scatter",
    label: "CHW leave reset vs web dry-bulb",
    family: "Plant",
    chart: "scatter",
    weatherAxis: "dry_bulb",
  },
  {
    id: "cw_reset_scatter",
    label: "CW / tower vs wet-bulb",
    family: "Plant",
    chart: "scatter",
    weatherAxis: "wet_bulb",
  },
  {
    id: "vav_flows",
    label: "VAV airflow",
    family: "VAV",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "fan_speeds",
    label: "Fan speeds",
    family: "AHU",
    chart: "timeseries",
    weatherAxis: "none",
  },
  {
    id: "meter_elec_cdd",
    label: "Electric vs CDD",
    family: "Metering",
    chart: "metering",
    weatherAxis: "none",
  },
  {
    id: "meter_gas_hdd",
    label: "Gas vs HDD",
    family: "Metering",
    chart: "metering",
    weatherAxis: "none",
  },
];

export const MAX_PLOT_POINTS = 5000;

export type RegistryRule = {
  rule_id: string;
  description: string;
  confirm_seconds: number;
  confirm_min?: number;
  required_roles: string[];
  parameter_count: number;
  parity_status?: string;
  dashboard_wired?: boolean;
};

export type RuleParamDef = {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  control: string;
  sql_placeholder: string;
};
