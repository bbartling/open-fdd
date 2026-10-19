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
  capabilities?: ProviderCapabilities;
}

export interface HistoryCapability {
  support?: string;
  method?: string | null;
  path?: string | null;
  max_window_secs?: number | null;
  reason?: string | null;
}

export interface ProviderCapabilities {
  latest?: string;
  catalog?: string;
  fetch_history?: HistoryCapability;
}

export interface ProvidersHealthBody {
  ok?: boolean;
  poll_enabled?: boolean;
  sites?: ProviderSiteHealth[];
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

/** Building ids from the provider registry. Empty when the call fails. */
export async function listProviderBuildingIds(): Promise<string[]> {
  try {
    const body = await fetchProviderSites();
    const ids = new Set<string>();
    for (const site of body.sites ?? []) {
      const id = (site.building_id ?? "").trim();
      if (id) ids.add(id);
    }
    for (const site of body.health ?? []) {
      const id = (site.building_id ?? "").trim();
      if (id) ids.add(id);
    }
    return [...ids].sort((a, b) => a.localeCompare(b));
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
