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
  optional_roles?: string[];
  confirm_seconds?: number;
  confirm_min?: number;
  parity_status?: string;
  dashboard_wired?: boolean;
  parameter_count?: number;
  sql_file?: string;
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
  /** Soft-OPEN R8f: bypass write-once skipped_recompute after fresh samples. */
  force_new_data?: boolean;
}

export interface FddRunTiming {
  rule_id?: string;
  status?: string;
  ms?: number;
  error?: string;
  [key: string]: unknown;
}

export interface FddMetricWindow {
  start?: string | null;
  end?: string | null;
  watermark?: string | null;
}

export interface FddMetricCoverage {
  sample_rows?: number | null;
}

export interface FddMetricValue {
  name?: string;
  value?: number | null;
  unit?: string;
  window?: FddMetricWindow;
  coverage?: FddMetricCoverage;
}

export interface FddResultRow {
  rule_id: string;
  title?: string;
  equipment_id: string;
  equipment_type?: string;
  status: string;
  output_kind?: string;
  fault_hours?: number | null;
  fault_pct?: number | null;
  metric?: FddMetricValue | null;
  values?: Record<string, number | null> | null;
  missing_roles?: string[];
  notes?: unknown;
  run_id?: string | null;
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
  run_id?: string | null;
  run_status?: string | null;
  result_count?: number;
  parent_run_id?: string | null;
  timings?: FddRunTiming[];
  results_dir?: string;
  results?: FddResultRow[];
  cache?: unknown;
  /** Soft-OPEN write-once: cohort already on file; prefer Lab single-rule. */
  skipped_recompute?: boolean;
  message?: string;
}

export interface FddResultsResponse {
  ok: boolean;
  count: number;
  results: FddResultRow[];
  run_id?: string | null;
  run_status?: string | null;
  parent_run_id?: string | null;
  error?: string;
}

export interface FddSeriesResponse {
  ok: boolean;
  equipment_id?: string;
  equipment_type?: string;
  rule_id?: string;
  roles?: string[];
  rows?: Array<Record<string, unknown>>;
  downsampled?: boolean;
  max_points?: number;
  has_confirmed_fault?: boolean;
  missing_roles?: string[];
  error?: string;
}

export const FDD_STATUS_PATH = "/api/fdd/status";
export const FDD_RULES_PATH = "/api/fdd/rules";
export const FDD_RUN_PATH = "/api/fdd/run";
export const FDD_RESULTS_PATH = "/api/fdd/results";
export const FDD_SERIES_PATH = "/api/fdd/series";
/** C12 lean Plotly — one rule+equip, catalog roles, max_points≈1500. */
export const FDD_PLOT_PATH = "/api/fdd/plot";
/** Soft-OPEN R4: lean plot role catalog per rule (Timescale). Soft-OPEN ≠ FQ. */
export const FDD_PLOTS_BY_RULE_PATH = "/api/fdd/plots-by-rule";

export interface FddPlotsByRuleLeanBudget {
  max_roles?: number;
  default_points?: number;
  hard_cap_points?: number;
}

export interface FddPlotsByRuleEntry {
  rule_id: string;
  roles?: string[];
  [key: string]: unknown;
}

export interface FddPlotsByRuleResponse {
  ok: boolean;
  engine?: string;
  lean_budget?: FddPlotsByRuleLeanBudget;
  rules?: FddPlotsByRuleEntry[];
  soft_open_neq_fq?: boolean;
  error?: string;
  note?: string;
}

export function buildFddResultsPath(buildingId?: string): string {
  if (!buildingId) return FDD_RESULTS_PATH;
  const q = new URLSearchParams({ building_id: buildingId });
  return `${FDD_RESULTS_PATH}?${q.toString()}`;
}

export function buildFddSeriesPath(
  equipmentId: string,
  ruleId: string,
  buildingId?: string,
): string {
  return buildFddPlotPath(equipmentId, ruleId, buildingId);
}

export function buildFddPlotPath(
  equipmentId: string,
  ruleId: string,
  buildingId?: string,
  opts?: { maxPoints?: number; windowStart?: string; windowEnd?: string },
): string {
  const q = new URLSearchParams({
    equipment_id: equipmentId,
    rule_id: ruleId,
  });
  if (buildingId) q.set("building_id", buildingId);
  q.set("max_points", String(opts?.maxPoints ?? 1500));
  if (opts?.windowStart) q.set("window_start", opts.windowStart);
  if (opts?.windowEnd) q.set("window_end", opts.windowEnd);
  return `${FDD_PLOT_PATH}?${q.toString()}`;
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
      ...(request.force_new_data ? { force_new_data: true } : {}),
    }),
    signal: init?.signal,
  });
  if (!body.ok) {
    throw new Error(body.error || "FDD run failed");
  }
  return body;
}

export async function getFddResultsDocument(
  buildingId?: string,
): Promise<FddResultsResponse> {
  const body = await apiFetch<FddResultsResponse>(buildFddResultsPath(buildingId));
  if (!body.ok) {
    throw new Error(body.error || "Failed to load FDD results");
  }
  return {
    ...body,
    count: Number(body.count ?? body.results?.length ?? 0),
    results: body.results ?? [],
  };
}

export async function getFddResults(buildingId?: string): Promise<FddResultRow[]> {
  const body = await getFddResultsDocument(buildingId);
  return body.results;
}

export interface FddReadiness {
  ok: boolean;
  has_results: boolean;
  clean: boolean;
  dirty_reasons: string[];
  completed_at?: string | null;
  result_count: number;
  run_id?: string | null;
  run_status?: string | null;
  parent_run_id?: string | null;
  cohort?: string | null;
  rules_succeeded?: number | null;
  rules_failed?: number | null;
  rules_skipped?: number | null;
  mode?: string | null;
  error?: string;
}

export function buildFddReadinessPath(buildingId?: string): string {
  const base = `${FDD_RESULTS_PATH}/readiness`;
  if (!buildingId) return base;
  const q = new URLSearchParams({ building_id: buildingId });
  return `${base}?${q.toString()}`;
}

export async function getFddReadiness(buildingId?: string): Promise<FddReadiness> {
  const body = await apiFetch<FddReadiness>(buildFddReadinessPath(buildingId));
  if (!body.ok) {
    throw new Error(body.error || "Failed to load FDD readiness");
  }
  return {
    ...body,
    dirty_reasons: Array.isArray(body.dirty_reasons) ? body.dirty_reasons : [],
    result_count: Number(body.result_count ?? 0),
    has_results: Boolean(body.has_results),
    clean: Boolean(body.clean),
  };
}

export async function getFddSeries(
  equipmentId: string,
  ruleId: string,
  buildingId?: string,
  init?: { signal?: AbortSignal; maxPoints?: number },
): Promise<FddSeriesResponse> {
  return getFddPlot(equipmentId, ruleId, buildingId, init);
}

/** Soft-OPEN R4: catalog lean-plot roles / budgets (no historian read). */
export async function listFddPlotsByRule(
  init?: { signal?: AbortSignal },
): Promise<FddPlotsByRuleResponse> {
  const body = await apiFetch<FddPlotsByRuleResponse>(FDD_PLOTS_BY_RULE_PATH, {
    signal: init?.signal,
  });
  if (!body.ok) {
    throw new Error(body.error || "Failed to load FDD plots-by-rule catalog");
  }
  return body;
}

/** Prefer server lean_budget.default_points; Soft-OPEN fallback 1500. */
export function leanPlotDefaultPoints(
  budget?: FddPlotsByRuleLeanBudget | null,
): number {
  const n = Number(budget?.default_points);
  if (Number.isFinite(n) && n > 0) return Math.floor(n);
  return 1500;
}

/** C12: abortable lean plot fetch (flip rule/equip → one request). */
export async function getFddPlot(
  equipmentId: string,
  ruleId: string,
  buildingId?: string,
  init?: { signal?: AbortSignal; maxPoints?: number },
): Promise<FddSeriesResponse> {
  const body = await apiFetch<FddSeriesResponse>(
    buildFddPlotPath(equipmentId, ruleId, buildingId, {
      maxPoints: init?.maxPoints ?? 1500,
    }),
    { signal: init?.signal },
  );
  if (!body.ok) {
    const missing = Array.isArray(body.missing_roles)
      ? body.missing_roles.filter(Boolean).join(", ")
      : "";
    throw new Error(
      missing
        ? `Rule unavailable — unmapped roles: ${missing}. Map roles on the equipment and re-seed Timescale, then retry.`
        : body.error || "Failed to load FDD plot",
    );
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
    "output_kind",
    "metric_name",
    "metric_value",
    "metric_unit",
    "metric_window_start",
    "metric_window_end",
    "metric_watermark",
    "metric_sample_rows",
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
        r.output_kind ?? "",
        r.metric?.name ?? "",
        r.metric?.value ?? "",
        r.metric?.unit ?? "",
        r.metric?.window?.start ?? "",
        r.metric?.window?.end ?? "",
        r.metric?.window?.watermark ?? "",
        r.metric?.coverage?.sample_rows ?? "",
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

export interface FddRuleParamDef {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  control: string;
  sql_placeholder: string;
}

export interface FddRuleParamsResponse {
  ok: boolean;
  rule_id?: string;
  confirm_seconds?: number;
  required_roles?: string[];
  params?: Record<string, FddRuleParamDef>;
  error?: string;
}

export function buildFddRuleParamsPath(ruleId: string): string {
  return `${FDD_RULES_PATH}/${encodeURIComponent(ruleId)}/params`;
}

export async function getFddRuleParams(ruleId: string): Promise<FddRuleParamsResponse> {
  const body = await apiFetch<FddRuleParamsResponse>(buildFddRuleParamsPath(ruleId));
  if (!body.ok) {
    throw new Error(body.error || `Failed to load params for ${ruleId}`);
  }
  return body;
}

/** Clamp numeric param to registry bounds; returns null if NaN. */
export function clampRuleParam(
  value: number,
  def: Pick<FddRuleParamDef, "min" | "max">,
): number | null {
  if (!Number.isFinite(value)) return null;
  return Math.min(def.max, Math.max(def.min, value));
}

/** Build session-config params map for one rule from slider values. */
export function buildRuleParamPayload(
  values: Record<string, number>,
  defs: Record<string, FddRuleParamDef>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, raw] of Object.entries(values)) {
    const def = defs[key];
    if (!def) continue;
    const clamped = clampRuleParam(raw, def);
    if (clamped == null) continue;
    out[key] = clamped;
  }
  return out;
}
