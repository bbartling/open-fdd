import { apiFetch } from "./client";

const TOKEN_KEY = "openfdd.auth.token";

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
}

export interface AuthLoginResponse {
  ok: boolean;
  token: string;
  access_token: string;
  token_type: string;
  role: string;
  subject: string;
  error?: string | null;
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
    if (!token) sessionStorage.removeItem(TOKEN_KEY);
    else sessionStorage.setItem(TOKEN_KEY, token);
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
}
