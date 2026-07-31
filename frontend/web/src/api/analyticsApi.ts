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
  return apiFetch<AnalyticsEnvelope>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
