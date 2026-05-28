const TOKEN_KEY = "ofdd_token";

export function getBridgeBase(): string {
  const override = localStorage.getItem("ofdd-bridge-base-override");
  if (override?.trim()) return override.replace(/\/$/, "");
  const env = import.meta.env.VITE_DESKTOP_BRIDGE_BASE as string | undefined;
  if (env?.trim()) return env.replace(/\/$/, "");
  return "";
}

function authHeaders(): HeadersInit {
  const token = sessionStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const base = getBridgeBase();
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401) {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function setToken(token: string) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function hasToken(): boolean {
  return Boolean(sessionStorage.getItem(TOKEN_KEY));
}

export type AuthStatus = { auth_required: boolean };

export async function fetchAuthStatus(): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/api/auth/status");
}

export async function login(username: string, password: string) {
  return apiFetch<{ token: string; username: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}
