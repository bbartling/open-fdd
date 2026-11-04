import { apiFetch } from "./client";

export const TOKEN_KEY = "openfdd.auth.token";
export const SESSION_GEN_KEY = "openfdd.auth.session_gen";

export interface AuthStatus {
  ok: boolean;
  auth_required: boolean;
  /** Present when central reports OPENFDD_AGENT_PASSWORD is configured. */
  agent_login_configured?: boolean;
}

export interface AuthMe {
  ok: boolean;
  username: string;
  role: string;
  auth_required: boolean;
  multi_tenant?: boolean;
  active_tenant_id?: string | null;
  tenant_ids?: string[];
  hub_admin?: boolean;
}

export interface AuthLoginResponse {
  ok: boolean;
  token: string;
  access_token: string;
  token_type: string;
  role: string;
  subject: string;
  multi_tenant?: boolean;
  active_tenant_id?: string | null;
  error?: string | null;
}

export function getSessionGeneration(): number {
  try {
    const raw = sessionStorage.getItem(SESSION_GEN_KEY);
    const n = raw ? Number(raw) : 0;
    return Number.isFinite(n) ? n : 0;
  } catch {
    return 0;
  }
}

/** Bump on login / token replace so late 401s from older requests cannot clear the new session. */
export function bumpSessionGeneration(): number {
  const next = Date.now();
  try {
    sessionStorage.setItem(SESSION_GEN_KEY, String(next));
  } catch {
    // ignore
  }
  return next;
}

export function getStoredToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (!token) {
      sessionStorage.removeItem(TOKEN_KEY);
      return;
    }
    bumpSessionGeneration();
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore
  }
}

export async function getAuthStatus(): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/api/auth/status");
}

export async function getAuthMe(): Promise<AuthMe> {
  return apiFetch<AuthMe>("/api/auth/me");
}

export async function login(
  username: string,
  password: string,
): Promise<AuthLoginResponse> {
  const body = await apiFetch<AuthLoginResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const token = body.access_token || body.token;
  if (body.ok && token) setStoredToken(token);
  return body;
}

export function logout(): void {
  setStoredToken(null);
  try {
    sessionStorage.removeItem(SESSION_GEN_KEY);
  } catch {
    // ignore
  }
}
