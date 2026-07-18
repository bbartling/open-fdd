import { apiFetch, apiUploadRaw } from "./api";

export type PackageEquipment = {
  equipment_id: string;
  column_count?: number;
  roles?: Record<string, string>;
  unmapped_columns?: string[];
  map_source?: string;
};

export type PackageImportResponse = {
  ok?: boolean;
  error?: string;
  hint?: string;
  missing_maps?: string[];
  schema_version?: string;
  building_id?: string;
  grid_minutes?: number;
  poll_seconds?: number;
  timezone?: string | null;
  equipment?: PackageEquipment[];
  equipment_written?: number;
  total_rows?: number;
  warnings?: string[];
  session_config?: Record<string, unknown> | null;
};

export type PackageRolesUpdateResponse = {
  ok?: boolean;
  error?: string;
  building_id?: string;
  equipment_id?: string;
  roles?: Record<string, string>;
  ignored_columns?: string[];
  total_rows?: number;
};

/** SQL cookbook logical roles (mirrors sql_rules/registry.yaml required_roles). */
export const COOKBOOK_ROLES: string[] = [
  "",
  "sat",
  "sat_sp",
  "mat",
  "rat",
  "oa_t",
  "oa_h",
  "oa_damper_pct",
  "clg_valve_pct",
  "htg_valve_pct",
  "fan_cmd",
  "fan_status",
  "return_fan",
  "duct_static",
  "duct_static_sp",
  "zone_t",
  "zone_flow",
  "min_flow_sp",
  "damper_pct",
  "reheat_valve_pct",
  "vav_discharge_t",
  "vav_inlet_t",
  "ahu_sat",
  "occ_mode",
  "chw_supply_t",
  "chw_return_t",
  "chw_supply_sp",
  "chw_dp",
  "chw_dp_sp",
  "chw_flow",
  "chw_pump_cmd",
  "cw_pump_cmd",
  "cw_supply_t",
  "cw_return_t",
  "tower_fan_cmd",
  "hw_supply_t",
  "hw_return_t",
  "preheat_leave_t",
  "web_oa_t",
  "web_oa_dp",
  "web_oa_h",
  "web_wb_t",
];

/** Upload an openfdd_package_v1 zip (raw body — binary safe). */
export async function uploadPackageZip(file: File): Promise<PackageImportResponse> {
  return apiUploadRaw<PackageImportResponse>(
    "/api/csv/import/package",
    file,
    "application/zip",
  );
}

/** Save edited role assignments for one equipment and re-ingest the building. */
export async function updatePackageRoles(
  buildingId: string,
  equipmentId: string,
  roles: Record<string, string>,
): Promise<PackageRolesUpdateResponse> {
  return apiFetch<PackageRolesUpdateResponse>("/api/csv/import/package/roles", {
    method: "POST",
    body: JSON.stringify({ building_id: buildingId, equipment_id: equipmentId, roles }),
  });
}
