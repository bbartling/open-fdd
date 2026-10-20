import type {
  ProviderBinding,
  ProviderRequestPreview,
  ProviderSiteConfig,
  ProviderSiteHealth,
} from "../api/providersApi";

export type StatusTone = "good" | "warn" | "bad" | "neutral";

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
  windowStart: string;
  windowEnd: string;
  state: string;
  requestedPoints: number | null;
  accepted: number | null;
  rejected: number | null;
  committed: number | null;
  retryCount: number | null;
  bytes: number | null;
  durationMs: number | null;
  jobId: string;
  recoverable: boolean | null;
  reason: string;
}

export type WindowLedgerView =
  | { available: true; windows: ProviderWindowRow[]; note: string }
  | { available: false; reason: string };

export interface SafeRequestPreview {
  method: "GET";
  path: string;
  note: string;
  pointCount: number | null;
}

export type BindingsView =
  | {
      available: true;
      bindings: ProviderBinding[];
      modelRevision: string | null;
      provider: string | null;
      preview: SafeRequestPreview | null;
      previewRefusal: string | null;
    }
  | { available: false; reason: string };

const SECRET_TEXT = /client_secret|authorization|bearer\s|access_token|refresh_token|token=/i;
const SECRET_QUERY_KEY = /secret|token|authorization|password/i;

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

function windowFromRaw(raw: unknown, index: number): ProviderWindowRow | null {
  const row = asRecord(raw);
  if (!row) return null;
  const deviceId = text(row.device_id) || text(row.equipment_id);
  const windowStart = text(row.window_start) || text(row.from) || text(row.logical_window_start);
  const windowEnd = text(row.window_end) || text(row.to) || text(row.logical_window_end);
  const state = text(row.state) || text(row.status) || "unknown";
  const jobId = text(row.job_id) || text(row.request_id) || text(row.id);
  if (!deviceId && !windowStart && !jobId) return null;
  const recoverable = boolOrNull(row.recoverable);
  return {
    id: jobId || `${deviceId}:${windowStart}:${index}`,
    deviceId,
    windowStart,
    windowEnd,
    state,
    requestedPoints: num(row.requested_points),
    accepted: num(row.accepted) ?? num(row.fetched),
    rejected: num(row.rejected),
    committed: num(row.committed) ?? num(row.upserted) ?? num(row.inserted),
    retryCount: num(row.retry_count),
    bytes: num(row.bytes) ?? num(row.response_bytes),
    durationMs: num(row.duration_ms),
    jobId: jobId || "—",
    recoverable,
    reason: text(row.reason) || text(row.safe_error_code),
  };
}

const LEDGER_ABSENT =
  "Window and gap ledger is not on this API yet. Durable per-device hourly jobs (N5) have not landed. Last poll and ingested counts above are connectivity snapshots, not coverage. A successful poll does not mean the completed hour is gap-free. NF update-log replication is not claimed.";

export function interpretWindowLedger(body: unknown, httpMissing: boolean): WindowLedgerView {
  if (httpMissing) return { available: false, reason: LEDGER_ABSENT };
  const record = asRecord(body);
  if (!record) {
    return {
      available: false,
      reason: "This response is not a window ledger. Poll health is not coverage.",
    };
  }
  if (record.available === false || record.implemented === false) {
    return {
      available: false,
      reason: text(record.reason) || LEDGER_ABSENT,
    };
  }
  const rawRows = Array.isArray(record.windows)
    ? record.windows
    : Array.isArray(record.jobs)
      ? record.jobs
      : null;
  if (!rawRows) {
    return {
      available: false,
      reason: "This response is not a window ledger. Poll health is not coverage.",
    };
  }
  const windows = rawRows
    .slice(0, 500)
    .map((row, index) => windowFromRaw(row, index))
    .filter((row): row is ProviderWindowRow => row != null);
  const note =
    windows.length === 0
      ? "Ledger is present and has no windows. That is not a green coverage result."
      : rawRows.length > 500
        ? "Showing the first 500 windows returned for this site."
        : "";
  return { available: true, windows, note };
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

export function interpretBindings(body: unknown, httpMissing: boolean): BindingsView {
  if (httpMissing) {
    return {
      available: false,
      reason:
        "Typed bindings are not published by this API yet (N3). Mapped-point counts on Operations are not a point list, and this screen will not invent a request.",
    };
  }
  const record = asRecord(body);
  if (!record) {
    return {
      available: false,
      reason: "Bindings response was empty. No request preview was generated in the browser.",
    };
  }
  if (record.available === false || record.implemented === false) {
    return {
      available: false,
      reason:
        text(record.reason) ||
        "Typed bindings are not published by this API yet (N3).",
    };
  }
  if (!Array.isArray(record.bindings)) {
    return {
      available: false,
      reason: "Bindings response had no binding list. No request preview was generated in the browser.",
    };
  }
  const bindings = (record.bindings as unknown[])
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => item != null)
    .slice(0, 500)
    .map((item) => ({
      provider_point_id: text(item.provider_point_id) || text(item.point_id),
      equipment_id: text(item.equipment_id),
      role: text(item.role) || text(item.canonical_role),
      equip_type: text(item.equip_type) || null,
      source_unit: text(item.source_unit) || null,
      canonical_unit: text(item.canonical_unit) || null,
      selection_status: text(item.selection_status) || text(item.approval_state) || null,
      kind: text(item.kind) || null,
      cadence: text(item.cadence) || null,
    }));
  const previewRaw = asRecord(record.request_preview);
  const previewInput: ProviderRequestPreview | null = previewRaw
    ? {
        method: text(previewRaw.method),
        path: text(previewRaw.path),
        note: text(previewRaw.note),
        point_count: num(previewRaw.point_count) ?? undefined,
        credentials_included: previewRaw.credentials_included === true,
      }
    : null;
  const safe = safeRequestPreview(previewInput);
  return {
    available: true,
    bindings,
    modelRevision: text(record.model_revision) || null,
    provider: text(record.provider) || null,
    preview: safe.preview,
    previewRefusal: safe.refusal,
  };
}
