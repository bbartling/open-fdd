import { apiFetch } from "./client";

export interface MappingColumnRow {
  column: string;
  role: string;
  status: "mapped" | "unmapped" | "ambiguous" | string;
}

export interface MappingSampling {
  ok?: boolean;
  row_count?: number;
  first_timestamp?: string | null;
  last_timestamp?: string | null;
  error?: string;
}

export interface MappingEquipment {
  equipment_id: string;
  equipment_type: string;
  parent_ahu?: string | null;
  ok: boolean;
  error?: string;
  columns?: MappingColumnRow[];
  roles?: Record<string, string>;
  unmapped_columns?: string[];
  ambiguous_roles?: Record<string, string[]>;
  sampling?: MappingSampling;
  blockers?: string[];
  warnings?: string[];
}

export interface MappingValidation {
  blocker_count: number;
  warning_count: number;
  equipment_count: number;
}

export interface PackageMappingResponse {
  ok: boolean;
  error?: string;
  hint?: string;
  building_id?: string;
  unit_system?: string;
  equipment_ids?: string[];
  equipment?: MappingEquipment[];
  session_role_map?: Record<string, Record<string, string>>;
  validation?: MappingValidation;
}

export interface PackageBuildingsResponse {
  ok: boolean;
  buildings: string[];
  path?: string;
  error?: string;
}

export interface UpdatePackageRolesResponse {
  ok: boolean;
  error?: string;
  building_id?: string;
  equipment_id?: string;
  roles?: Record<string, string>;
  ignored_columns?: string[];
  equipment_written?: number;
  total_rows?: number;
}

export interface SessionConfigResponse {
  ok: boolean;
  persisted?: boolean;
  path?: string;
  config?: SessionConfig;
  error?: string;
  warnings?: string[];
  applied_role_map?: Array<{ equipment_id: string; ok: boolean }>;
}

export interface SessionConfig {
  schema_version?: string;
  unit_system?: string;
  prefer_web_oat?: boolean;
  chw_leave_max_f?: number;
  role_map?: Record<string, Record<string, string>>;
  params?: Record<string, Record<string, number>>;
}

export const PACKAGE_MAPPING_PATH = "/api/csv/import/package/mapping";
export const PACKAGE_BUILDINGS_PATH = "/api/csv/import/package/buildings";
export const PACKAGE_ROLES_PATH = "/api/csv/import/package/roles";
export const SESSION_CONFIG_PATH = "/api/fdd/session-config";
export const FDD_ROLES_PATH = "/api/fdd/roles";

export function buildPackageMappingPath(
  buildingId: string,
  equipmentId?: string,
): string {
  const q = new URLSearchParams();
  q.set("building_id", buildingId);
  if (equipmentId) q.set("equipment_id", equipmentId);
  return `${PACKAGE_MAPPING_PATH}?${q.toString()}`;
}

export async function listPackageBuildings(): Promise<string[]> {
  const body = await apiFetch<PackageBuildingsResponse>(PACKAGE_BUILDINGS_PATH);
  if (!body.ok) {
    throw new Error(body.error || "Failed to list package buildings");
  }
  return body.buildings ?? [];
}

export async function getPackageMapping(
  buildingId: string,
  equipmentId?: string,
): Promise<PackageMappingResponse> {
  const body = await apiFetch<PackageMappingResponse>(
    buildPackageMappingPath(buildingId, equipmentId),
  );
  if (!body.ok) {
    throw new Error(body.error || "Failed to load package mapping");
  }
  return body;
}

/** Persist column→role map for one equipment and re-ingest parquet. */
export async function updatePackageRoles(
  buildingId: string,
  equipmentId: string,
  roles: Record<string, string>,
): Promise<UpdatePackageRolesResponse> {
  const body = await apiFetch<UpdatePackageRolesResponse>(PACKAGE_ROLES_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      building_id: buildingId,
      equipment_id: equipmentId,
      roles,
    }),
  });
  if (!body.ok) {
    throw new Error(body.error || "Failed to update package roles");
  }
  return body;
}

export async function getSessionConfig(): Promise<SessionConfigResponse> {
  return apiFetch<SessionConfigResponse>(SESSION_CONFIG_PATH);
}

/**
 * Save session config. When buildingId is set, Rust applies role_map
 * (role→column) onto package equipment via columns.csv rewrite.
 */
export async function putSessionConfig(
  config: SessionConfig,
  buildingId?: string,
): Promise<SessionConfigResponse> {
  const payload =
    buildingId && buildingId.trim()
      ? { building_id: buildingId, config }
      : config;
  const body = await apiFetch<SessionConfigResponse>(SESSION_CONFIG_PATH, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!body.ok) {
    throw new Error(body.error || "Failed to save session config");
  }
  return body;
}

export async function getFddRolesCatalog(): Promise<unknown> {
  return apiFetch(FDD_ROLES_PATH);
}

/** Invert column→role to role→column for session_config.role_map. */
export function invertRolesToSessionMap(
  columnRoles: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [column, role] of Object.entries(columnRoles)) {
    const r = role.trim();
    if (!r) continue;
    out[r] = column;
  }
  return out;
}

/** Build a downloadable mapping/validation manifest (client-side JSON). */
export function buildMappingManifest(
  inventory: PackageMappingResponse,
): string {
  return JSON.stringify(
    {
      schema: "openfdd_mapping_manifest_v1",
      generated_at: new Date().toISOString(),
      building_id: inventory.building_id,
      unit_system: inventory.unit_system,
      validation: inventory.validation,
      equipment: (inventory.equipment ?? []).map((eq) => ({
        equipment_id: eq.equipment_id,
        equipment_type: eq.equipment_type,
        parent_ahu: eq.parent_ahu ?? null,
        roles: eq.roles ?? {},
        unmapped_columns: eq.unmapped_columns ?? [],
        ambiguous_roles: eq.ambiguous_roles ?? {},
        blockers: eq.blockers ?? [],
        warnings: eq.warnings ?? [],
        sampling: eq.sampling ?? null,
        ok: eq.ok,
      })),
    },
    null,
    2,
  );
}
