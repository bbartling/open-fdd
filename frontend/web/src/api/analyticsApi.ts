import { apiFetch } from "./client";

/** Shared `/api/analytics/*` query fields (mirrors Rust AnalyticsQuery). */
export interface AnalyticsQuery {
  job_id?: string;
  run_id?: string;
  building_id?: string;
  equipment_ids?: string[];
  start?: string;
  end?: string;
  max_points?: number;
  query_version?: string;
}

export interface AnalyticsRequest extends AnalyticsQuery {
  samples?: unknown[];
  series?: unknown;
  max_gap_seconds?: number;
  dt_min_f?: number;
}

export interface AnalyticsEnvelope {
  schema_version: string;
  query_version: string;
  job_id?: string | null;
  run_id?: string | null;
  input_fingerprint?: string | null;
  generated_at: string;
  engine: string;
  coverage?: Record<string, unknown> | null;
  warnings: string[];
  rows: Record<string, unknown>[];
  equipment: Record<string, unknown>[];
  points: Record<string, unknown>[];
  skipped: Record<string, unknown>[];
}

/** Wire shape from central: `{ ok, analytics: <envelope> }` (see routes.rs). */
export interface AnalyticsApiResponse {
  ok?: boolean;
  analytics?: AnalyticsEnvelope;
  error?: string;
}

/** Normalize flat envelope or `{ok,analytics}` wrapper into a usable envelope. */
export function unwrapAnalyticsEnvelope(
  body: AnalyticsApiResponse | AnalyticsEnvelope | null | undefined,
): AnalyticsEnvelope {
  const empty: AnalyticsEnvelope = {
    schema_version: "",
    query_version: "",
    generated_at: "",
    engine: "",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  };
  if (!body || typeof body !== "object") return empty;
  const nested =
    "analytics" in body && body.analytics && typeof body.analytics === "object"
      ? body.analytics
      : (body as AnalyticsEnvelope);
  return {
    schema_version: String(nested.schema_version ?? ""),
    query_version: String(nested.query_version ?? ""),
    job_id: nested.job_id ?? null,
    run_id: nested.run_id ?? null,
    input_fingerprint: nested.input_fingerprint ?? null,
    generated_at: String(nested.generated_at ?? ""),
    engine: String(nested.engine ?? ""),
    coverage: nested.coverage ?? null,
    warnings: Array.isArray(nested.warnings) ? nested.warnings : [],
    rows: Array.isArray(nested.rows) ? nested.rows : [],
    equipment: Array.isArray(nested.equipment) ? nested.equipment : [],
    points: Array.isArray(nested.points) ? nested.points : [],
    skipped: Array.isArray(nested.skipped) ? nested.skipped : [],
  };
}

export interface MeterRow {
  period: string;
  kwh: number;
  meter_id?: string | null;
}

export interface MonthlySumRow {
  period: string;
  kwh: number;
  meter_id?: string | null;
  n_rows: number;
}

export interface FddEquipmentItem {
  equipment_id: string;
  equipment_type?: string;
  building_id?: string;
  [key: string]: unknown;
}

export interface FddEquipmentResponse {
  ok?: boolean;
  equipment?: FddEquipmentItem[];
  count?: number;
  [key: string]: unknown;
}

export async function postAnalytics(
  path: string,
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  const raw = await apiFetch<AnalyticsApiResponse | AnalyticsEnvelope>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (
    raw &&
    typeof raw === "object" &&
    "ok" in raw &&
    (raw as AnalyticsApiResponse).ok === false
  ) {
    throw new Error(
      (raw as AnalyticsApiResponse).error || `Analytics failed: ${path}`,
    );
  }
  return unwrapAnalyticsEnvelope(raw);
}

export async function postMetering(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/metering", body);
}

export async function postRcxAhu(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/rcx/ahu", body);
}

export async function postRcxVav(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/rcx/vav", body);
}

export async function postRuntime(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/runtime", body);
}

export async function postMechanicalCooling(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/mechanical-cooling", body);
}

export async function postBasVsWebOat(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/bas-vs-web-oat", body);
}

export async function postInspect(
  body: AnalyticsRequest & { series?: { columns?: string[] } },
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/inspect", body);
}

export async function postEconomizer(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/economizer", body);
}

export async function postSchedule(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/schedule", body);
}

export async function postSensorHealth(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/sensor-health", body);
}

export async function postVavHealth(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/vav-health", body);
}

export async function postRcxChiller(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/rcx/chiller", body);
}

export async function postRcxBoiler(
  body: AnalyticsRequest,
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/rcx/boiler", body);
}

export async function postRcxPreset(
  body: AnalyticsRequest & { series?: { preset_id?: string } },
): Promise<AnalyticsEnvelope> {
  return postAnalytics("/api/analytics/rcx/preset", body);
}

export async function listRcxPresets(): Promise<
  Array<{
    id: string;
    title: string;
    family: string;
    chart: string;
    role_col?: string;
    frozen?: boolean;
  }>
> {
  const body = await apiFetch<{
    ok?: boolean;
    presets?: Array<Record<string, unknown>>;
  }>("/api/analytics/rcx/presets");
  const raw = Array.isArray(body.presets) ? body.presets : [];
  return raw.map((p) => ({
    id: String(p.id ?? ""),
    title: String(p.title ?? p.id ?? ""),
    family: String(p.family ?? ""),
    chart: String(p.chart ?? "timeseries"),
    role_col: p.role_col != null ? String(p.role_col) : undefined,
    frozen: Boolean(p.frozen),
  }));
}

export async function listFddEquipment(
  buildingId?: string,
): Promise<FddEquipmentItem[]> {
  const q = buildingId
    ? `?building_id=${encodeURIComponent(buildingId)}`
    : "";
  const body = await apiFetch<FddEquipmentResponse>(`/api/fdd/equipment${q}`);
  return Array.isArray(body.equipment) ? body.equipment : [];
}

/** Pure client aggregation mirror of Rust monthly_sum (parity helper). */
export function monthlySumClient(rows: MeterRow[]): MonthlySumRow[] {
  const map = new Map<string, { kwh: number; n_rows: number; meter_id?: string | null }>();
  for (const r of rows) {
    if (!Number.isFinite(r.kwh)) continue;
    const key = `${r.period}\0${r.meter_id ?? ""}`;
    const cur = map.get(key) ?? { kwh: 0, n_rows: 0, meter_id: r.meter_id };
    cur.kwh += r.kwh;
    cur.n_rows += 1;
    map.set(key, cur);
  }
  return [...map.entries()]
    .map(([key, v]) => {
      const period = key.split("\0")[0] ?? "";
      return {
        period,
        kwh: Math.round(v.kwh * 10_000) / 10_000,
        meter_id: v.meter_id,
        n_rows: v.n_rows,
      };
    })
    .sort((a, b) => a.period.localeCompare(b.period));
}

export const SAMPLE_METER_ROWS: MeterRow[] = [
  { period: "2024-01", kwh: 100 },
  { period: "2024-01", kwh: 50.5 },
  { period: "2024-02", kwh: 200 },
  { period: "2024-03", kwh: 175.25 },
];
