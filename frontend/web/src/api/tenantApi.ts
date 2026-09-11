import { apiFetch } from "./client";
import { setStoredToken } from "./authApi";

const ACTIVE_TENANT_KEY = "openfdd.tenant.active";

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
