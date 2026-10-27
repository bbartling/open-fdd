import type { OptionalFetch } from "../api/providersApi";
import type { StatusTone } from "./providerDisplay";

/** One provider row from `GET /api/ingest/gaps?view=status`. */
export interface CoverageStatusRow {
  key: string;
  providerInstanceId: string;
  mode: string;
  timezone: string | null;
  nextRun: string | null;
  plannedThrough: string | null;
  scheduleError: string | null;
  verifiedThrough: string | null;
  approvedPoints: number | null;
  discoveredPoints: number | null;
  withheldPoints: number | null;
  state: string;
  stateReason: string | null;
  oldestGap: string | null;
  gapScanTruncated: boolean;
}

export type CoverageStatusView =
  | { status: "ready"; state: string; stateReason: string | null; rows: CoverageStatusRow[] }
  | { status: "unavailable"; reason: string }
  | { status: "error"; message: string };

const STATE_LABELS: Record<string, string> = {
  verified: "Verified",
  behind: "Behind schedule",
  gap: "Gap",
  not_assessed: "Not assessed",
  not_configured: "No committed plan",
};

const STATE_REASON_LABELS: Record<string, string> = {
  cadence_not_bound:
    "Committed model points have no cadence binding (history_mode, cadence_secs, or heartbeat_secs from NF metadata or the model overlay). Coverage stays not assessed until cadence is bound.",
  no_verified_cursor: "No verified hourly cursor yet for this provider.",
  coverage_not_assessed: "Coverage is not assessed for this provider.",
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Label for a coverage state. Unknown states are named, never shown as verified. */
export function coverageStateLabel(state: string): string {
  return STATE_LABELS[state] ?? `Unrecognized state (${state || "missing"})`;
}

export function coverageStateTone(state: string): StatusTone {
  if (state === "verified") return "good";
  if (state === "behind") return "warn";
  if (state === "gap") return "bad";
  return "neutral";
}

export function coverageStateReasonLabel(reason: string): string {
  const key = reason.trim();
  return STATE_REASON_LABELS[key] ?? `Not assessed (${key || "unknown"})`;
}

function oldestGapText(value: unknown): string | null {
  const gap = record(value);
  if (!gap) return null;
  const parts = [
    text(gap.device_id) ?? "unknown device",
    `${text(gap.start) ?? "—"} → ${text(gap.end) ?? "—"}`,
    text(gap.state) ?? "unknown state",
  ];
  const code = text(gap.code);
  if (code) parts.push(code);
  return parts.join(" · ");
}

function rowFrom(value: unknown, index: number): CoverageStatusRow {
  const provider = record(value) ?? {};
  const schedule = record(provider.schedule) ?? {};
  const status = record(provider.status) ?? {};
  const providerInstanceId = text(status.provider_instance_id) ?? "unknown provider";
  return {
    key: `${text(provider.tenant_id) ?? ""}:${providerInstanceId}:${index}`,
    providerInstanceId,
    mode: text(schedule.mode) ?? "unknown",
    timezone: text(schedule.timezone),
    nextRun: text(provider.next_run),
    plannedThrough: text(provider.planned_through),
    scheduleError: text(provider.schedule_error),
    verifiedThrough: text(status.verified_through),
    approvedPoints: count(status.approved_points),
    discoveredPoints: count(status.discovered_points),
    withheldPoints: count(status.withheld_points),
    state: text(status.state) ?? "",
    stateReason: text(status.state_reason),
    oldestGap: oldestGapText(status.oldest_gap),
    gapScanTruncated: provider.gap_scan_truncated === true,
  };
}

/** Reads the fetch result. A body without a providers list is an error, not an empty site. */
export function coverageStatusFromFetch(fetched: OptionalFetch): CoverageStatusView {
  if (fetched.http === "missing") {
    return {
      status: "unavailable",
      reason: "Coverage status is not available for this site on this API.",
    };
  }
  if (fetched.http === "error") return { status: "error", message: fetched.message };
  const body = record(fetched.body);
  if (!body || !Array.isArray(body.providers)) {
    return { status: "error", message: "Coverage status response has no providers list." };
  }
  return {
    status: "ready",
    state: text(body.state) ?? "",
    stateReason: text(body.state_reason),
    rows: body.providers.map(rowFrom),
  };
}

/** Points text. Missing counts stay missing rather than reading as zero. */
export function pointsText(row: CoverageStatusRow): string {
  const approved = row.approvedPoints ?? "—";
  const discovered = row.discoveredPoints ?? "—";
  const withheld = row.withheldPoints === null ? "" : ` (${row.withheldPoints} withheld)`;
  return `${approved} of ${discovered}${withheld}`;
}
