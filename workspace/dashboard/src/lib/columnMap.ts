import { apiFetch } from "./api";

/** Versioned CSV column→FDD-role mapping (Phase 1 / #481). */
export type ColumnMapDocument = {
  version: number;
  dataset_id: string;
  timezone: string;
  timestamp_column: string;
  equipment: string;
  /** CSV header → FDD role. Never auto-filled. */
  column_map: Record<string, string>;
};

export type ColumnMapValidation = {
  ok: boolean;
  errors: string[];
};

export const COLUMN_MAP_SCHEMA_VERSION = 1;

/** Empty scaffold — does not invent column→role pairs. */
export function emptyColumnMapDocument(datasetId = ""): ColumnMapDocument {
  return {
    version: COLUMN_MAP_SCHEMA_VERSION,
    dataset_id: datasetId,
    timezone: "",
    timestamp_column: "",
    equipment: "",
    column_map: {},
  };
}

export function normalizeColumnMapDocument(raw: unknown): ColumnMapDocument {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const column_map: Record<string, string> = {};
  const mapRaw = obj.column_map;
  if (mapRaw && typeof mapRaw === "object" && !Array.isArray(mapRaw)) {
    for (const [k, v] of Object.entries(mapRaw as Record<string, unknown>)) {
      const col = k.trim();
      const role = typeof v === "string" ? v.trim() : "";
      if (col && role) column_map[col] = role;
    }
  }
  const version =
    typeof obj.version === "number" && Number.isFinite(obj.version)
      ? Math.trunc(obj.version)
      : COLUMN_MAP_SCHEMA_VERSION;
  return {
    version,
    dataset_id: typeof obj.dataset_id === "string" ? obj.dataset_id.trim() : "",
    timezone: typeof obj.timezone === "string" ? obj.timezone.trim() : "",
    timestamp_column:
      typeof obj.timestamp_column === "string" ? obj.timestamp_column.trim() : "",
    equipment: typeof obj.equipment === "string" ? obj.equipment.trim() : "",
    column_map,
  };
}

/** Required meta fields + no duplicate roles. Empty column_map is allowed (explicit draft). */
export function validateColumnMapDocument(doc: ColumnMapDocument): ColumnMapValidation {
  const errors: string[] = [];
  if (!Number.isInteger(doc.version) || doc.version < 1) {
    errors.push("version must be an integer >= 1");
  }
  if (!doc.dataset_id.trim()) errors.push("dataset_id is required");
  if (!doc.timezone.trim()) errors.push("timezone is required");
  if (!doc.timestamp_column.trim()) errors.push("timestamp_column is required");
  if (!doc.equipment.trim()) errors.push("equipment is required");

  const seenRoles = new Map<string, string>();
  for (const [col, role] of Object.entries(doc.column_map)) {
    const c = col.trim();
    const r = role.trim();
    if (!c) {
      errors.push("column_map keys must be non-empty column names");
      continue;
    }
    if (!r) {
      errors.push(`column_map[${c}] role must be non-empty`);
      continue;
    }
    const prior = seenRoles.get(r);
    if (prior) {
      errors.push(`duplicate role '${r}' mapped from columns '${prior}' and '${c}'`);
    } else {
      seenRoles.set(r, c);
    }
  }

  return { ok: errors.length === 0, errors };
}

export function parseColumnMapJson(text: string): ColumnMapDocument {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("Invalid JSON");
  }
  if (parsed && typeof parsed === "object" && "mapping" in (parsed as object)) {
    return normalizeColumnMapDocument((parsed as { mapping: unknown }).mapping);
  }
  return normalizeColumnMapDocument(parsed);
}

export function exportColumnMapJson(doc: ColumnMapDocument): string {
  return `${JSON.stringify(normalizeColumnMapDocument(doc), null, 2)}\n`;
}

export type ColumnMapApiResponse = {
  ok?: boolean;
  mapping?: ColumnMapDocument;
  error?: string;
  path?: string;
};

export async function fetchColumnMap(datasetId?: string): Promise<ColumnMapDocument> {
  const qs = datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : "";
  const res = await apiFetch<ColumnMapApiResponse>(`/api/fdd/mapping${qs}`);
  if (res.error) throw new Error(res.error);
  return normalizeColumnMapDocument(res.mapping ?? emptyColumnMapDocument(datasetId ?? ""));
}

export async function saveColumnMap(doc: ColumnMapDocument): Promise<ColumnMapDocument> {
  const normalized = normalizeColumnMapDocument(doc);
  const check = validateColumnMapDocument(normalized);
  if (!check.ok) throw new Error(check.errors.join("; "));
  const res = await apiFetch<ColumnMapApiResponse>("/api/fdd/mapping", {
    method: "PUT",
    body: JSON.stringify({ mapping: normalized }),
  });
  if (res.ok === false || res.error) throw new Error(res.error ?? "save failed");
  return normalizeColumnMapDocument(res.mapping ?? normalized);
}

/** Common FDD role ids for datalist hints only — never auto-assigned. */
export const SUGGESTED_FDD_ROLES = [
  "oa_t",
  "oa_h",
  "sat",
  "duct_t",
  "zn_t",
  "sat_sp",
  "fan_cmd",
  "occ",
] as const;
