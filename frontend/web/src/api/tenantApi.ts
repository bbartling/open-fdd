import { apiFetch } from "./client";
import { setStoredToken } from "./authApi";
import { RULE_PARAMS_STORAGE_KEY } from "../lib/ruleParams";
import { clearAllFormDrafts } from "../session/sessionQuery";

const ACTIVE_TENANT_KEY = "openfdd.tenant.active";

/** Fired after a successful tenant switch so open views drop the previous site. */
export const TENANT_CHANGED_EVENT = "openfdd:tenant-changed";

export interface TenantsListResponse {
  ok: boolean;
  multi_tenant: boolean;
  active_tenant_id?: string | null;
  buildings_visible?: string[];
  historian_prefix?: string;
  tenants: Array<{ id: string; name: string; building_ids?: string[] }>;
}

export interface TenantSelectResponse {
  ok: boolean;
  multi_tenant: boolean;
  active_tenant_id: string;
  token?: string | null;
  access_token?: string | null;
  error?: string | null;
}

export function getStoredActiveTenant(): string | null {
  try {
    return sessionStorage.getItem(ACTIVE_TENANT_KEY);
  } catch {
    return null;
  }
}

export function setStoredActiveTenant(tenantId: string | null): void {
  try {
    if (!tenantId) sessionStorage.removeItem(ACTIVE_TENANT_KEY);
    else sessionStorage.setItem(ACTIVE_TENANT_KEY, tenantId);
  } catch {
    // ignore
  }
}

/**
 * Drop client state that belongs to the previous active tenant.
 * The session token and the stored active-tenant id stay; the caller
 * replaces those from the select response.
 */
export function clearTenantScopedClientState(): void {
  clearAllFormDrafts();
  try {
    localStorage.removeItem(RULE_PARAMS_STORAGE_KEY);
  } catch {
    // localStorage can be unavailable.
  }
  window.dispatchEvent(new CustomEvent(TENANT_CHANGED_EVENT));
}

export async function listTenants(): Promise<TenantsListResponse> {
  return apiFetch<TenantsListResponse>("/api/tenants");
}

/** Select active tenant (single-domain). OFF mode: only `legacy` no-op. */
export async function selectTenant(
  tenantId: string,
): Promise<TenantSelectResponse> {
  const body = await apiFetch<TenantSelectResponse>("/api/tenants/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  if (body.ok && body.active_tenant_id) {
    setStoredActiveTenant(body.active_tenant_id);
  }
  const token = body.access_token || body.token;
  if (body.ok && token) setStoredToken(token);
  return body;
}
