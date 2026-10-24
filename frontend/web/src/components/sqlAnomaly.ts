import { naturalCompare } from "../lib/naturalSort";

/** Event-table contract shared with the Timescale `sql-anomaly` route. */
export const SQL_ANOMALY_QUERY_VERSION = "sql-anomaly-event-v1";

export const SQL_ANOMALY_ROW_KEYS = [
  "anomaly_flag",
  "avg_val",
  "equipment_id",
  "method",
  "role",
  "stddev_val",
  "threshold",
  "transition",
  "ts",
  "val",
  "z_abs",
] as const;

const SUMMARY_KEYS = ["score", "anomaly_hours", "anomaly_events", "last_at"] as const;

const SERIES_REASONS = new Set([
  "missing_values",
  "short_history",
  "constant_history",
  "scored",
]);

export type AnomalySeriesReason =
  | "missing_values"
  | "short_history"
  | "constant_history"
  | "scored";

export interface AnomalyEvent {
  anomaly_flag: "ANOMALY";
  avg_val: number;
  equipment_id: string;
  method: "zscore";
  role: string;
  stddev_val: number;
  threshold: number;
  transition: boolean;
  ts: string;
  val: number;
  z_abs: number;
  row_key: string;
}

export interface AnomalySeries {
  equipment_id: string;
  role: string;
  reason: AnomalySeriesReason;
  n: number;
  n_null: number;
}

export interface AnomalyCoverage {
  contract: string;
  semantics: string;
  method: string;
  window_rows: number;
  z_threshold: number;
  transition_events: boolean;
  truncated: boolean;
  window_start: string | null;
  window_end: string | null;
  n_samples: number;
  n_scored: number;
  n_flagged: number;
  n_ok: number;
  n_returned: number;
  series: AnomalySeries[];
}

export interface ParsedAnomaly {
  queryVersion: string;
  warnings: string[];
  rows: AnomalyEvent[];
  coverage: AnomalyCoverage;
  /** Matching version, no rows, and no coverage object (empty client mock). */
  uncoveredEmpty: boolean;
}

export interface AnomalyEnvelopeInput {
  query_version?: string;
  warnings?: unknown;
  rows?: unknown;
  coverage?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function contractError(): Error {
  return new Error("Anomaly response does not match the event contract.");
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function requiredNumber(value: unknown): number {
  const number = finiteNumber(value);
  if (number == null) throw contractError();
  return number;
}

function requiredText(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) throw contractError();
  return value;
}

function emptyCoverage(): AnomalyCoverage {
  return {
    contract: "event-table",
    semantics: "rolling-prior-window-zscore",
    method: "zscore",
    window_rows: 0,
    z_threshold: 0,
    transition_events: false,
    truncated: false,
    window_start: null,
    window_end: null,
    n_samples: 0,
    n_scored: 0,
    n_flagged: 0,
    n_ok: 0,
    n_returned: 0,
    series: [],
  };
}

function parseSeries(value: unknown): AnomalySeries[] {
  if (value == null) return [];
  if (!Array.isArray(value)) throw contractError();
  return value.map((item) => {
    if (!isRecord(item)) throw contractError();
    const reason = requiredText(item.reason);
    if (!SERIES_REASONS.has(reason)) throw contractError();
    return {
      equipment_id: requiredText(item.equipment_id),
      role: requiredText(item.role),
      reason: reason as AnomalySeriesReason,
      n: requiredNumber(item.n),
      n_null: requiredNumber(item.n_null),
    };
  });
}

function optionalStamp(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function parseCoverage(value: unknown): AnomalyCoverage | null {
  if (value == null) return null;
  if (!isRecord(value)) throw contractError();
  return {
    contract: typeof value.contract === "string" ? value.contract : "",
    semantics: typeof value.semantics === "string" ? value.semantics : "",
    method: typeof value.method === "string" ? value.method : "",
    window_rows: requiredNumber(value.window_rows),
    z_threshold: requiredNumber(value.z_threshold),
    transition_events: value.transition_events === true,
    truncated: value.truncated === true,
    window_start: optionalStamp(value.window_start),
    window_end: optionalStamp(value.window_end),
    n_samples: requiredNumber(value.n_samples),
    n_scored: requiredNumber(value.n_scored),
    n_flagged: requiredNumber(value.n_flagged),
    n_ok: requiredNumber(value.n_ok),
    n_returned: requiredNumber(value.n_returned),
    series: parseSeries(value.series),
  };
}

function parseEvent(value: unknown): AnomalyEvent {
  if (!isRecord(value)) throw contractError();
  for (const key of SUMMARY_KEYS) {
    if (key in value) throw contractError();
  }
  const keys = Object.keys(value).sort();
  if (
    keys.length !== SQL_ANOMALY_ROW_KEYS.length ||
    keys.some((key, index) => key !== SQL_ANOMALY_ROW_KEYS[index])
  ) {
    throw contractError();
  }
  const anomalyFlag = requiredText(value.anomaly_flag);
  const method = requiredText(value.method);
  if (anomalyFlag !== "ANOMALY" || method !== "zscore") throw contractError();
  const equipmentId = requiredText(value.equipment_id);
  const role = requiredText(value.role);
  const ts = requiredText(value.ts);
  if (typeof value.transition !== "boolean") throw contractError();
  return {
    anomaly_flag: "ANOMALY",
    avg_val: requiredNumber(value.avg_val),
    equipment_id: equipmentId,
    method: "zscore",
    role,
    stddev_val: requiredNumber(value.stddev_val),
    threshold: requiredNumber(value.threshold),
    transition: value.transition,
    ts,
    val: requiredNumber(value.val),
    z_abs: requiredNumber(value.z_abs),
    row_key: `${equipmentId}|${role}|${ts}`,
  };
}

function warningList(value: unknown): string[] {
  if (value == null) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw contractError();
  }
  return value;
}

/** Reject a summary-shaped or wrong-version payload instead of rendering blanks. */
export function parseAnomalyEnvelope(env: AnomalyEnvelopeInput): ParsedAnomaly {
  if ((env.query_version ?? "") !== SQL_ANOMALY_QUERY_VERSION) {
    throw contractError();
  }
  const warnings = warningList(env.warnings);
  const rawRows = env.rows == null ? [] : env.rows;
  if (!Array.isArray(rawRows)) throw contractError();
  const coverage = parseCoverage(env.coverage);
  if (rawRows.length === 0 && coverage == null) {
    return {
      queryVersion: SQL_ANOMALY_QUERY_VERSION,
      warnings,
      rows: [],
      coverage: emptyCoverage(),
      uncoveredEmpty: true,
    };
  }
  return {
    queryVersion: SQL_ANOMALY_QUERY_VERSION,
    warnings,
    rows: rawRows.map(parseEvent),
    coverage: coverage ?? emptyCoverage(),
    uncoveredEmpty: coverage == null,
  };
}

export function sortAnomalyEvents(rows: readonly AnomalyEvent[]): AnomalyEvent[] {
  return [...rows].sort((left, right) => {
    if (left.z_abs !== right.z_abs) return right.z_abs - left.z_abs;
    if (left.ts !== right.ts) return left.ts < right.ts ? 1 : -1;
    const equipment = naturalCompare(left.equipment_id, right.equipment_id);
    if (equipment !== 0) return equipment;
    return naturalCompare(left.role, right.role);
  });
}

export function parseWindowRows(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  if (!Number.isInteger(value) || value < 3 || value > 168) return null;
  return value;
}

/** Positive threshold the Overview control can send. 10 and 30 stay distinct. */
export function parseZThreshold(text: string): number | null {
  const value = Number(text.trim());
  if (!Number.isFinite(value) || value <= 0 || value > 100) return null;
  return value;
}

/** Up to 6 fractional digits, trailing zeros removed (`80.125` stays `80.125`). */
export function formatAnomalyNumber(value: number): string {
  if (!Number.isFinite(value)) return "";
  const fixed = value.toFixed(6);
  if (!fixed.includes(".")) return fixed;
  return fixed.replace(/0+$/, "").replace(/\.$/, "");
}

/** UTC clock from `Date.toISOString`, never the browser local zone. */
export function formatAnomalyTimestamp(ts: string): string {
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;
  return parsed.toISOString().replace("T", " ").replace(".000Z", "Z");
}

function onlyReason(parsed: ParsedAnomaly, reason: AnomalySeriesReason): boolean {
  return (
    parsed.coverage.series.length > 0 &&
    parsed.coverage.series.every((row) => row.reason === reason)
  );
}

export function anomalyEmptyNote(parsed: ParsedAnomaly): string | null {
  if (parsed.rows.length > 0) return null;
  if (parsed.warnings.some((warning) => warning.includes("disabled"))) {
    return "SQL anomaly screening is disabled on this central (OPENFDD_SQL_ANOMALY_SCREENING=0).";
  }
  const unsupported = parsed.warnings.find((warning) => warning.includes("not supported"));
  if (unsupported) return unsupported;
  if (parsed.uncoveredEmpty || parsed.coverage.series.length === 0) {
    if (
      parsed.uncoveredEmpty ||
      parsed.warnings.some((warning) => warning.includes("no screened samples"))
    ) {
      return "No screened samples in this window.";
    }
  }
  if (onlyReason(parsed, "missing_values")) {
    return "Screened points have no numeric history in this window.";
  }
  if (onlyReason(parsed, "short_history")) {
    return "History is shorter than the window, so no anomaly events were scored.";
  }
  if (onlyReason(parsed, "constant_history")) {
    return "History has no variance, so no anomaly events were scored.";
  }
  if (parsed.warnings.some((warning) => warning.includes("no screened samples"))) {
    return "No screened samples in this window.";
  }
  if (parsed.coverage.n_flagged === 0) {
    return "No anomaly events at this threshold.";
  }
  return null;
}

export function anomalyEdgeNote(parsed: ParsedAnomaly): string | null {
  if (!parsed.coverage.transition_events) return null;
  if (parsed.coverage.n_flagged <= parsed.rows.length) return null;
  return `Showing rising edges. ${parsed.coverage.n_flagged} flagged samples in this window.`;
}
