import type {
  OptionalFetch,
  ProviderRequestPreview,
  ProviderSiteConfig,
  ProviderSiteHealth,
} from "../api/providersApi";

export type StatusTone = "good" | "warn" | "bad" | "neutral";

/**
 * Coverage token shared by the jobs list and the gaps list.
 * The two lists still have separate contracts: a jobs `complete` is a receipt
 * summary, and a gaps `not_assessed` (including an empty gap list) is not that receipt.
 */
export type IngestCoverage = "complete" | "incomplete" | "not_assessed";

export interface ProviderStatusView {
  tone: StatusTone;
  label: string;
  detail: string;
}

export interface ProviderRow {
  key: string;
  buildingId: string;
  provider: string;
  endpoint?: string;
  pollSecs?: number;
  mappedPoints?: number;
  clientIdConfigured?: boolean;
  lastPollAt?: string | null;
  lastSuccessAt?: string | null;
  lastErrorAt?: string | null;
  lastIngested?: number;
  consecutiveErrors?: number;
  status?: string;
  message?: string | null;
}

export interface ProviderWindowRow {
  id: string;
  deviceId: string;
  providerInstanceId: string;
  modelRevision: string;
  windowStart: string;
  windowEnd: string;
  state: string;
  fetched: number | null;
  accepted: number | null;
  rejected: number | null;
  inserted: number | null;
  attempt: number | null;
  bytes: number | null;
  durationMs: number | null;
  jobId: string;
  recoverable: boolean | null;
  reason: string;
  /** Jobs-list coverage. Complete is a receipt summary, not a gaps result. */
  coverage: IngestCoverage;
}

export interface JobIdentityBinding {
  key: string;
  providerInstanceId: string;
  deviceId: string;
  modelRevision: string;
  windowCount: number;
}

export const BOUNDED_WINDOW_COVERAGE_LABEL =
  "Bounded-window coverage. Coverage is not assessed. Update-log replication is not claimed. This is not a gap-free ingest claim.";

export const POLL_LEDGER_COVERAGE_LABEL =
  "Bounded-window coverage. A poll snapshot does not establish gap-free ingest.";

const MISSING_INGEST_ENDPOINT =
  "The ingest jobs or gaps endpoint is not on this API. A missing endpoint is not coverage and is not a gap-free ingest.";

const INGEST_LEDGER_ERROR =
  "Ingest jobs or gaps could not be loaded. Poll health is unchanged, and this is not a gap-free result.";

export type WindowLedgerView =
  | {
      status: "ready";
      coverageLabel: string;
      jobsCoverage: IngestCoverage;
      gapsCoverage: IngestCoverage;
      jobs: ProviderWindowRow[];
      gaps: ProviderWindowRow[];
      jobsNote: string;
      gapsNote: string;
    }
  | { status: "unavailable"; reason: string };

export interface SafeRequestPreview {
  method: "GET";
  path: string;
  note: string;
  pointCount: number | null;
}

const SECRET_TEXT = /client_secret|authorization|bearer\s|access_token|refresh_token|token=/i;
const SECRET_QUERY_KEY = /secret|token|authorization|password/i;

const ARCHIVED_FIELD_DRIVERS = new Set([
  "mqtt",
  "mqtts",
  "bacnet",
  "modbus",
  "haystack",
  "fieldbus",
]);

/** Archived OT drivers are not product ingest. NF and CSV stay visible. */
export function isArchivedFieldDriver(kind: string | null | undefined): boolean {
  return ARCHIVED_FIELD_DRIVERS.has((kind ?? "").trim().toLowerCase());
}

export function providerLabel(kind: string | null | undefined): string {
  const k = (kind ?? "").trim().toLowerCase();
  if (k === "nf" || k === "normal" || k === "normal_framework") return "NF";
  if (k === "ace_iot" || k === "ace" || k === "ace-iot") return "Ace IoT";
  if (!k) return "—";
  return kind!.trim();
}

export function sanitizeProviderOrigin(endpoint: string | null | undefined): string {
  const raw = (endpoint ?? "").trim();
  if (!raw) return "—";
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" && url.protocol !== "http:") return "unsupported scheme";
    return url.origin;
  } catch {
    return "unreadable endpoint";
  }
}

export function providerStatusView(input: {
  status?: string | null;
  consecutiveErrors?: number | null;
  lastPollAt?: string | null;
  message?: string | null;
}): ProviderStatusView {
  const status = (input.status ?? "").trim().toLowerCase();
  const errors = input.consecutiveErrors ?? 0;
  const message = (input.message ?? "").trim();
  if (status === "ok" && errors === 0 && input.lastPollAt) {
    return {
      tone: "good",
      label: "Poll ok",
      detail: "Last poll reported success. This is not a committed-window or gap ledger.",
    };
  }
  if (status === "ok") {
    return {
      tone: "neutral",
      label: "Poll reported ok",
      detail: input.lastPollAt
        ? "Consecutive errors are non-zero, so this is not a clean poll."
        : "No last-poll timestamp. An outer ok flag is not coverage.",
    };
  }
  if (status === "degraded") {
    return { tone: "warn", label: "Degraded", detail: message || "Poll is degraded." };
  }
  if (status === "auth_failed") {
    return {
      tone: "bad",
      label: "Auth failed",
      detail: message || "Credential or token was rejected.",
    };
  }
  if (status === "error") {
    return { tone: "bad", label: "Error", detail: message || "Provider reported an error." };
  }
  if (status === "not_configured") {
    return {
      tone: "neutral",
      label: "Not configured",
      detail: message || "Connection is not configured for polling.",
    };
  }
  if (status === "not_implemented") {
    return {
      tone: "neutral",
      label: "Not implemented",
      detail: "This driver does not poll.",
    };
  }
  return {
    tone: "neutral",
    label: "Unknown",
    detail: "No provider status was returned. Outer health flags are not coverage.",
  };
}

export function staticDriverNotes(provider: string | null | undefined): string[] {
  const kind = (provider ?? "").trim().toLowerCase();
  if (kind === "nf" || kind === "normal" || kind === "normal_framework") {
    return [
      "History read is GET /api/v1/point/data. POST on that path is a write and is not a poll.",
      "Latest scrape may use POST /api/v1/point/query. That call is separate from history coverage.",
      "Update-log replication is not claimed. Hourly reads stay bounded when the source log is unavailable.",
      "These lines are the documented driver contract, not a live capability probe.",
    ];
  }
  if (kind === "ace_iot" || kind === "ace" || kind === "ace-iot") {
    return ["Ace IoT is NotImplemented. No history poll is performed."];
  }
  return ["No static driver notes for this provider kind."];
}

export function siteSourceLabels(input: {
  hasPackage: boolean;
  provider?: string | null;
}): string[] {
  const out: string[] = [];
  if (input.hasPackage) out.push("CSV package");
  if ((input.provider ?? "").trim()) out.push(providerLabel(input.provider));
  return out;
}

export function credentialRefLabel(configured: boolean | undefined): string {
  if (configured === true) return "reference present";
  if (configured === false) return "not configured";
  return "not reported";
}

const STATUS_WITHOUT_ERROR_TEXT = new Set(["ok", "not_configured", "not_implemented"]);

/** Healthy poll copy stays out of the Last error column. */
export function lastErrorText(input: {
  status?: string | null;
  message?: string | null;
  lastErrorAt?: string | null;
}): string {
  const status = (input.status ?? "").trim().toLowerCase();
  const message = (input.message ?? "").trim();
  if (message && !STATUS_WITHOUT_ERROR_TEXT.has(status)) return message;
  const at = (input.lastErrorAt ?? "").trim();
  return at || "—";
}

/** `last_ingested_points` is a sample count. It is not a clock time. */
export function lastIngestedPointsText(count: number | null | undefined): string {
  if (typeof count !== "number" || !Number.isFinite(count)) return "—";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
    useGrouping: true,
  }).format(Math.trunc(count));
}

function rowKey(buildingId: string, provider: string): string {
  return `${buildingId}\u0000${provider}`;
}

export function mergeProviderRows(
  health: ProviderSiteHealth[] | undefined,
  configs: ProviderSiteConfig[] | undefined,
): ProviderRow[] {
  const map = new Map<string, ProviderRow>();
  const upsert = (buildingId: string, provider: string): ProviderRow => {
    const key = rowKey(buildingId, provider);
    const existing = map.get(key);
    if (existing) return existing;
    const row: ProviderRow = { key, buildingId, provider };
    map.set(key, row);
    return row;
  };
  for (const site of configs ?? []) {
    const buildingId = (site.building_id ?? "").trim();
    if (!buildingId) continue;
    const row = upsert(buildingId, (site.provider ?? "").trim());
    row.endpoint = site.endpoint ?? row.endpoint;
    row.pollSecs = site.poll_secs ?? row.pollSecs;
    row.mappedPoints = site.mapped_points ?? row.mappedPoints;
    row.clientIdConfigured = site.client_id_configured ?? row.clientIdConfigured;
  }
  for (const site of health ?? []) {
    const buildingId = (site.building_id ?? "").trim();
    if (!buildingId) continue;
    const row = upsert(buildingId, (site.provider ?? site.health?.kind ?? "").trim());
    row.endpoint = site.endpoint ?? row.endpoint;
    row.pollSecs = site.poll_secs ?? row.pollSecs;
    row.mappedPoints = site.mapped_points ?? row.mappedPoints;
    row.lastPollAt = site.last_poll_at ?? row.lastPollAt;
    row.lastSuccessAt = site.health?.last_success_at ?? row.lastSuccessAt;
    row.lastErrorAt = site.health?.last_error_at ?? row.lastErrorAt;
    row.lastIngested = site.last_ingested_points ?? row.lastIngested;
    row.consecutiveErrors = site.consecutive_errors ?? row.consecutiveErrors;
    row.status = site.health?.status ?? row.status;
    row.message = site.health?.message ?? row.message;
  }
  return [...map.values()].sort((a, b) =>
    a.buildingId.localeCompare(b.buildingId) || a.provider.localeCompare(b.provider),
  );
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function boolOrNull(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

const GAPS_GUARANTEE = "bounded_windows_only";
const UPDATE_LOG_NOT_CLAIMED = "not_claimed";

function claimsGapFree(record: Record<string, unknown>): boolean {
  if (record.gapless === true) return true;
  const guarantee = asRecord(record.guarantee);
  return guarantee?.gapless === true;
}

/** Jobs and gaps both emit these three tokens. Other words belong to the other list. */
function parseListedCoverage(value: unknown, allowAbsent: boolean): IngestCoverage | null {
  if (value == null) return allowAbsent ? "not_assessed" : null;
  if (typeof value !== "string") return null;
  const raw = value.trim();
  if (!raw) return allowAbsent ? "not_assessed" : null;
  if (raw === "complete" || raw === "incomplete" || raw === "not_assessed") return raw;
  return null;
}

export function jobsCoverageLabel(coverage: IngestCoverage): string {
  if (coverage === "complete") {
    return "Bounded-window coverage. Job coverage is complete. A complete receipt is not proof that history has no gaps. This is not a gap-free ingest claim.";
  }
  if (coverage === "incomplete") {
    return "Bounded-window coverage. Job coverage is incomplete. Incomplete belongs to the jobs list, not the gaps list. This is not a gap-free ingest claim.";
  }
  return BOUNDED_WINDOW_COVERAGE_LABEL;
}

export function jobCoverageWord(coverage: IngestCoverage): string {
  if (coverage === "complete") return "Complete";
  if (coverage === "incomplete") return "Incomplete";
  return "Not assessed";
}

function gapsNoteText(gaps: ProviderWindowRow[], coverage: IngestCoverage): string {
  const base =
    gaps.length === 0
      ? "No gaps in the returned windows. An empty gap list is not gap-free ingest."
      : "Partial, failed, and retry windows in the bounded list. These rows are not a device-hour completeness proof.";
  if (coverage === "not_assessed") return base;
  if (coverage === "incomplete") return `${base} Gaps coverage is incomplete.`;
  return `${base} Gaps coverage complete applies only to returned gap rows. It is not proof that history has no gaps.`;
}

function windowFromJob(raw: unknown, recoverable: boolean | null): ProviderWindowRow | null {
  const row = asRecord(raw);
  if (!row) return null;
  const jobId = text(row.job_id);
  if (!jobId) return null;
  const counts = asRecord(row.counts);
  const coverage = parseListedCoverage(row.coverage, true);
  if (!coverage) return null;
  return {
    id: jobId,
    deviceId: text(row.device_id),
    providerInstanceId: text(row.provider_instance_id),
    modelRevision: text(row.model_revision),
    windowStart: text(row.logical_window_start),
    windowEnd: text(row.logical_window_end),
    state: text(row.state) || "unknown",
    fetched: num(counts?.fetched),
    accepted: num(counts?.accepted),
    rejected: num(counts?.rejected),
    inserted: num(counts?.inserted),
    attempt: num(row.attempt),
    bytes: num(row.bytes),
    durationMs: num(row.duration_ms),
    jobId,
    recoverable,
    reason: text(row.safe_error_code),
    coverage,
  };
}

function jobsFromEnvelope(
  body: unknown,
): { coverage: IngestCoverage; jobs: ProviderWindowRow[] } | null {
  const record = asRecord(body);
  if (!record || claimsGapFree(record)) return null;
  const coverage = parseListedCoverage(record.coverage, false);
  if (!coverage || !Array.isArray(record.jobs)) return null;
  const rows = record.jobs.slice(0, 500).map((row) => windowFromJob(row, null));
  if (rows.some((row) => row == null)) return null;
  return { coverage, jobs: rows.filter((row): row is ProviderWindowRow => row != null) };
}

function gapsFromEnvelope(
  body: unknown,
): { coverage: IngestCoverage; gaps: ProviderWindowRow[] } | null {
  const record = asRecord(body);
  if (!record || claimsGapFree(record)) return null;
  const coverage = parseListedCoverage(record.coverage, false);
  if (!coverage) return null;
  if (text(record.guarantee) !== GAPS_GUARANTEE) return null;
  if (text(record.update_log) !== UPDATE_LOG_NOT_CLAIMED) return null;
  if (!Array.isArray(record.gaps)) return null;
  const rows = record.gaps.slice(0, 500).map((row) => {
    const wrapper = asRecord(row);
    if (!wrapper) return null;
    const recoverable = boolOrNull(wrapper.recoverable);
    if (recoverable == null) return null;
    return windowFromJob(wrapper.job, recoverable);
  });
  if (rows.some((row) => row == null)) return null;
  return { coverage, gaps: rows.filter((row): row is ProviderWindowRow => row != null) };
}

export function interpretIngestLedger(jobsBody: unknown, gapsBody: unknown): WindowLedgerView {
  const jobsParsed = jobsFromEnvelope(jobsBody);
  const gapsParsed = gapsFromEnvelope(gapsBody);
  if (!jobsParsed || !gapsParsed) {
    return {
      status: "unavailable",
      reason:
        "This response is not the ingest jobs and gaps contract. Coverage was not assessed from it, and it is not shown as gap-free.",
    };
  }
  const { jobs } = jobsParsed;
  const { gaps } = gapsParsed;
  const jobsNote =
    jobs.length === 0
      ? "No durable job windows were returned. That is not a green coverage result."
      : "Durable job windows and retries. These rows are not a device-hour completeness proof.";
  return {
    status: "ready",
    coverageLabel: jobsCoverageLabel(jobsParsed.coverage),
    jobsCoverage: jobsParsed.coverage,
    gapsCoverage: gapsParsed.coverage,
    jobs,
    gaps,
    jobsNote,
    gapsNote: gapsNoteText(gaps, gapsParsed.coverage),
  };
}

export function ledgerFromFetches(jobs: OptionalFetch, gaps: OptionalFetch): WindowLedgerView {
  if (jobs.http === "error" || gaps.http === "error") {
    return { status: "unavailable", reason: INGEST_LEDGER_ERROR };
  }
  if (jobs.http === "missing" || gaps.http === "missing") {
    return { status: "unavailable", reason: MISSING_INGEST_ENDPOINT };
  }
  return interpretIngestLedger(jobs.body, gaps.body);
}

export function jobIdentityBindings(jobs: ProviderWindowRow[]): JobIdentityBinding[] {
  const map = new Map<string, JobIdentityBinding>();
  for (const job of jobs) {
    const key = `${job.providerInstanceId}\u0000${job.deviceId}\u0000${job.modelRevision}`;
    const existing = map.get(key);
    map.set(key, {
      key,
      providerInstanceId: job.providerInstanceId,
      deviceId: job.deviceId,
      modelRevision: job.modelRevision,
      windowCount: (existing?.windowCount ?? 0) + 1,
    });
  }
  return [...map.values()].sort(
    (a, b) =>
      a.providerInstanceId.localeCompare(b.providerInstanceId) ||
      a.deviceId.localeCompare(b.deviceId) ||
      a.modelRevision.localeCompare(b.modelRevision),
  );
}

export function windowStateLabel(row: ProviderWindowRow): string {
  const state = row.state.toLowerCase();
  if (row.recoverable === false || state.includes("unrecover")) {
    return "Unrecoverable";
  }
  if (state === "committed") return "Committed";
  if (state === "partial") return "Partial";
  if (state === "retry_wait" || state === "retrying") return "Retry wait";
  if (state === "permanent_failure" || state === "failed") return "Failed";
  if (state === "queued" || state === "leased") return state === "leased" ? "Leased" : "Queued";
  return row.state || "Unknown";
}

export function windowTone(row: ProviderWindowRow): StatusTone {
  const label = windowStateLabel(row);
  if (label === "Committed") return "good";
  if (label === "Partial" || label === "Retry wait" || label === "Queued" || label === "Leased") {
    return "warn";
  }
  if (label === "Unrecoverable" || label === "Failed") return "bad";
  return "neutral";
}

const PREVIEW_REFUSAL_CREDENTIALS =
  "Request preview was refused because the payload was marked as containing credentials.";
const PREVIEW_REFUSAL_WRITE =
  "POST /api/v1/point/data is a write and is not shown as a history poll.";

export function safeRequestPreview(
  preview: ProviderRequestPreview | null | undefined,
): { preview: SafeRequestPreview | null; refusal: string | null } {
  if (!preview) return { preview: null, refusal: null };
  if (preview.credentials_included === true) {
    return { preview: null, refusal: PREVIEW_REFUSAL_CREDENTIALS };
  }
  const method = (preview.method ?? "").trim().toUpperCase();
  const path = (preview.path ?? "").trim();
  const note = (preview.note ?? "").trim();
  if (method === "POST" && path.includes("/api/v1/point/data")) {
    return { preview: null, refusal: PREVIEW_REFUSAL_WRITE };
  }
  if (method !== "GET" || !path.startsWith("/") || path.includes("://")) {
    return {
      preview: null,
      refusal: "Request preview was omitted because it was not a relative GET path.",
    };
  }
  let parsed: URL;
  try {
    parsed = new URL(path, "https://preview.invalid");
  } catch {
    return { preview: null, refusal: "Request preview path could not be read." };
  }
  if (parsed.username || parsed.password || parsed.hash) {
    return { preview: null, refusal: PREVIEW_REFUSAL_CREDENTIALS };
  }
  if (SECRET_TEXT.test(parsed.pathname) || SECRET_TEXT.test(note)) {
    return { preview: null, refusal: PREVIEW_REFUSAL_CREDENTIALS };
  }
  const kept = new URLSearchParams();
  parsed.searchParams.forEach((value, key) => {
    if (SECRET_QUERY_KEY.test(key) || SECRET_TEXT.test(value)) return;
    kept.append(key, value);
  });
  const query = kept.toString();
  return {
    preview: {
      method: "GET",
      path: query ? `${parsed.pathname}?${query}` : parsed.pathname,
      note: note || "Server-issued preview. No credentials are included.",
      pointCount: num(preview.point_count),
    },
    refusal: null,
  };
}

export function illustratedNfHistoryRead(pointCount: number | null): string {
  const n = pointCount == null ? "N" : String(pointCount);
  return `GET /api/v1/point/data?uuids=<${n} opaque ids>&from.seconds=<window>&to.seconds=<window>`;
}
