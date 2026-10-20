import { ApiClientError, apiFetch } from "./client";

/** Poll snapshot from `GET /api/providers/health`. Outer `ok` is not coverage. */
export interface ProviderSiteHealth {
  building_id?: string;
  provider?: string;
  endpoint?: string;
  poll_secs?: number;
  mapped_points?: number;
  last_poll_at?: string | null;
  last_ingested_points?: number;
  consecutive_errors?: number;
  health?: {
    status?: string;
    message?: string | null;
    provider_id?: string;
    kind?: string;
    last_success_at?: string | null;
    last_error_at?: string | null;
  };
  capabilities?: ProviderCapabilityView[];
  /** N7 six-axis ledger. Absent until an hourly tick has run. */
  coverage_ledger?: CoverageLedgerView | null;
}

export interface ProviderCapabilityView {
  name: string;
  support: string;
  http_method?: string | null;
  path?: string | null;
  note?: string | null;
}

export interface ProviderRegistrationView {
  kind: string;
  capabilities: ProviderCapabilityView[];
}

export interface CoverageAxisView {
  id: string;
  state: string;
  detail: string;
}

export interface CoverageLedgerView {
  guarantee?: { statement?: string; gapless?: boolean };
  axes?: CoverageAxisView[];
  gapless?: boolean;
  advanced_by_latest_sample?: boolean;
  windows_complete?: number;
}

export interface ProvidersHealthBody {
  ok?: boolean;
  poll_enabled?: boolean;
  sites?: ProviderSiteHealth[];
  registry?: ProviderRegistrationView[];
}

export interface ProviderSiteConfig {
  building_id?: string;
  provider?: string;
  endpoint?: string;
  poll_secs?: number;
  mapped_points?: number;
  client_id_configured?: boolean;
}

export interface ProviderSitesBody {
  ok?: boolean;
  poll_enabled?: boolean;
  sites?: ProviderSiteConfig[];
  health?: ProviderSiteHealth[];
}

export interface ProviderBinding {
  provider_point_id?: string;
  equipment_id?: string;
  role?: string;
  equip_type?: string | null;
  source_unit?: string | null;
  canonical_unit?: string | null;
  selection_status?: string | null;
  kind?: string | null;
  cadence?: string | null;
}

export interface ProviderRequestPreview {
  method?: string;
  path?: string;
  note?: string;
  point_count?: number;
  credentials_included?: boolean;
}

export interface ProviderBindingsBody {
  ok?: boolean;
  available?: boolean;
  reason?: string;
  building_id?: string;
  provider?: string;
  model_revision?: string | null;
  bindings?: ProviderBinding[];
  request_preview?: ProviderRequestPreview | null;
}

export type OptionalFetch =
  | { http: "ok"; body: unknown }
  | { http: "missing" }
  | { http: "error"; message: string };

export async function fetchProvidersHealth(): Promise<ProvidersHealthBody> {
  return apiFetch<ProvidersHealthBody>("/api/providers/health");
}

export async function fetchProviderSites(): Promise<ProviderSitesBody> {
  return apiFetch<ProviderSitesBody>("/api/providers/sites");
}

/** Sites with mapped points. Zero-point rows stay off the Active site picker. */
export function buildingIdsFromProviderSites(body: ProviderSitesBody): string[] {
  const ids = new Set<string>();
  const consider = (site: { building_id?: string; mapped_points?: number } | undefined) => {
    const id = (site?.building_id ?? "").trim();
    if (!id || (site?.mapped_points ?? 0) <= 0) return;
    ids.add(id);
  };
  for (const site of body.sites ?? []) consider(site);
  for (const site of body.health ?? []) consider(site);
  return [...ids].sort((a, b) => a.localeCompare(b));
}

/** Building ids from the provider registry. Empty when the call fails. */
export async function listProviderBuildingIds(): Promise<string[]> {
  try {
    return buildingIdsFromProviderSites(await fetchProviderSites());
  } catch {
    return [];
  }
}

export async function fetchOptionalJson(path: string): Promise<OptionalFetch> {
  try {
    const body = await apiFetch<unknown>(path);
    return { http: "ok", body };
  } catch (err) {
    if (err instanceof ApiClientError && (err.status === 404 || err.status === 501)) {
      return { http: "missing" };
    }
    const message = err instanceof Error ? err.message : String(err);
    return { http: "error", message };
  }
}

export function providerWindowsPath(buildingId: string): string {
  const q = new URLSearchParams();
  q.set("building_id", buildingId);
  return `/api/providers/windows?${q.toString()}`;
}

export function providerBindingsPath(buildingId: string): string {
  const q = new URLSearchParams();
  q.set("building_id", buildingId);
  return `/api/providers/bindings?${q.toString()}`;
}
