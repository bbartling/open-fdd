import { apiFetch } from "./client";

export interface FddStatus {
  ok: boolean;
  rules_dir: string;
  rules_dir_exists: boolean;
  rule_count: number;
  hint?: string;
}

export interface FddRuleSummary {
  rule_id: string;
  description?: string;
  aliases?: string[];
  equipment_kinds?: string[];
  required_roles?: string[];
  confirm_seconds?: number;
  [key: string]: unknown;
}

export interface FddRulesListResponse {
  ok: boolean;
  count?: number;
  rules_dir?: string;
  rules?: FddRuleSummary[];
  error?: string;
}

export interface FddRunRequest {
  mode?: string;
  rule_ids?: string[];
  equipment_id?: string;
  building_id?: string;
  params?: Record<string, Record<string, number>>;
  confirmation_seconds?: number;
}

export interface FddRunTiming {
  rule_id?: string;
  status?: string;
  ms?: number;
  error?: string;
  [key: string]: unknown;
}

export interface FddResultRow {
  rule_id: string;
  title?: string;
  equipment_id: string;
  equipment_type?: string;
  status: string;
  fault_hours?: number;
  fault_pct?: number | null;
  missing_roles?: string[];
  notes?: unknown;
}

export interface FddRunResponse {
  ok: boolean;
  error?: string;
  engine?: string;
  mode?: string;
  building_id?: string | null;
  history_root?: string;
  rules_run?: number;
  rules_succeeded?: number;
  rules_failed?: number;
  rules_skipped?: number;
  poll_seconds?: number;
  total_ms?: number;
  timings?: FddRunTiming[];
  results_dir?: string;
  results?: FddResultRow[];
  cache?: unknown;
}

export interface FddResultsResponse {
  ok: boolean;
  count: number;
  results: FddResultRow[];
  error?: string;
}

export interface FddSeriesResponse {
  ok: boolean;
  equipment_id?: string;
  rule_id?: string;
  rows?: unknown[];
  error?: string;
}

export const FDD_STATUS_PATH = "/api/fdd/status";
export const FDD_RULES_PATH = "/api/fdd/rules";
export const FDD_RUN_PATH = "/api/fdd/run";
export const FDD_RESULTS_PATH = "/api/fdd/results";
export const FDD_SERIES_PATH = "/api/fdd/series";

export function buildFddResultsPath(buildingId?: string): string {
  if (!buildingId) return FDD_RESULTS_PATH;
  const q = new URLSearchParams({ building_id: buildingId });
  return `${FDD_RESULTS_PATH}?${q.toString()}`;
}

export function buildFddSeriesPath(equipmentId: string, ruleId: string): string {
  const q = new URLSearchParams({
    equipment_id: equipmentId,
    rule_id: ruleId,
  });
  return `${FDD_SERIES_PATH}?${q.toString()}`;
}

export async function getFddStatus(): Promise<FddStatus> {
  return apiFetch<FddStatus>(FDD_STATUS_PATH);
}

export async function listFddRules(): Promise<FddRuleSummary[]> {
  const body = await apiFetch<FddRulesListResponse>(FDD_RULES_PATH);
  if (!body.ok) {
    throw new Error(body.error || "Failed to list FDD rules");
  }
  return body.rules ?? [];
}

/** Synchronous registry run (central blocks until DataFusion finishes). */
export async function runFdd(
  request: FddRunRequest,
  init?: { signal?: AbortSignal },
): Promise<FddRunResponse> {
  const body = await apiFetch<FddRunResponse>(FDD_RUN_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: request.mode ?? "registry",
      rule_ids: request.rule_ids,
      equipment_id: request.equipment_id,
      building_id: request.building_id,
      params: request.params ?? {},
      confirmation_seconds: request.confirmation_seconds,
    }),
    signal: init?.signal,
  });
  if (!body.ok) {
    throw new Error(body.error || "FDD run failed");
  }
  return body;
}

export async function getFddResults(buildingId?: string): Promise<FddResultRow[]> {
  const body = await apiFetch<FddResultsResponse>(buildFddResultsPath(buildingId));
  if (!body.ok) {
    throw new Error(body.error || "Failed to load FDD results");
  }
  return body.results ?? [];
}

export async function getFddSeries(
  equipmentId: string,
  ruleId: string,
): Promise<FddSeriesResponse> {
  const body = await apiFetch<FddSeriesResponse>(
    buildFddSeriesPath(equipmentId, ruleId),
  );
  if (!body.ok) {
    throw new Error(body.error || "Failed to load FDD series");
  }
  return body;
}

/** Download helper — JSON artifact of current results. */
export function resultsToJsonArtifact(
  rows: FddResultRow[],
  meta?: Record<string, unknown>,
): string {
  return JSON.stringify(
    {
      schema: "openfdd_fdd_results_v1",
      generated_at: new Date().toISOString(),
      ...meta,
      count: rows.length,
      results: rows,
    },
    null,
    2,
  );
}

/** CSV artifact — stable column order for parity diffs. */
export function resultsToCsvArtifact(rows: FddResultRow[]): string {
  const header = [
    "rule_id",
    "equipment_id",
    "equipment_type",
    "status",
    "fault_hours",
    "fault_pct",
    "missing_roles",
    "title",
  ];
  const escape = (v: unknown) => {
    const s = v == null ? "" : String(v);
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [header.join(",")];
  for (const r of rows) {
    lines.push(
      [
        r.rule_id,
        r.equipment_id,
        r.equipment_type ?? "",
        r.status,
        r.fault_hours ?? "",
        r.fault_pct ?? "",
        (r.missing_roles ?? []).join("|"),
        r.title ?? "",
      ]
        .map(escape)
        .join(","),
    );
  }
  return lines.join("\n");
}

export function downloadTextFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
