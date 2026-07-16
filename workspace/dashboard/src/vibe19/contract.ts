/** Frozen vibe19 dashboard sections — mirror app/dashboard_contract.py */

export const VIBE19_SECTIONS = [
  "Overview",
  "Data Model",
  "Run Rules",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
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
] as const;

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
