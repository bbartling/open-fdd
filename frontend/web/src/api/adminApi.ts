import { apiFetch } from "./client";

export type AdminUser = {
  username: string;
  role: string;
  tenant_ids: string[];
  password_env?: string | null;
  has_inline_password: boolean;
  disabled: boolean;
};

export type AdminTenant = {
  id: string;
  name: string;
  building_ids?: string[];
};

export async function listAdminUsers(): Promise<AdminUser[]> {
  const body = await apiFetch<{ ok?: boolean; users?: AdminUser[] }>("/api/admin/users");
  return body.users ?? [];
}

export async function upsertAdminUser(input: {
  username: string;
  role: string;
  tenant_ids: string[];
  password?: string;
  password_env?: string;
  disabled?: boolean;
}): Promise<AdminUser[]> {
  const body = await apiFetch<{ ok?: boolean; users?: AdminUser[]; error?: string }>(
    "/api/admin/users",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (body.ok === false) throw new Error(body.error || "upsert failed");
  return body.users ?? [];
}

export async function setAdminUserDisabled(username: string, disabled: boolean): Promise<void> {
  await apiFetch(`/api/admin/users/${encodeURIComponent(username)}/disabled`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ disabled }),
  });
}

export async function deleteAdminUser(username: string): Promise<void> {
  await apiFetch(`/api/admin/users/${encodeURIComponent(username)}`, {
    method: "DELETE",
  });
}

export async function listAdminTenants(): Promise<AdminTenant[]> {
  const body = await apiFetch<{ ok?: boolean; tenants?: AdminTenant[] }>("/api/admin/tenants");
  return body.tenants ?? [];
}

export async function upsertAdminTenant(input: {
  id: string;
  name: string;
  building_ids: string[];
}): Promise<AdminTenant[]> {
  const body = await apiFetch<{ ok?: boolean; tenants?: AdminTenant[]; error?: string }>(
    "/api/admin/tenants",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (body.ok === false) throw new Error(body.error || "upsert failed");
  return body.tenants ?? [];
}

export async function deleteAdminTenant(tenantId: string): Promise<void> {
  await apiFetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}`, {
    method: "DELETE",
  });
}
