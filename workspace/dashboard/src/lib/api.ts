const TOKEN_KEY = "ofdd_token";
const BRIDGE_OVERRIDE_KEY = "ofdd-bridge-base-override";

function isLocalhostHost(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}

function resolveBase(candidate: string, pageHost: string): string {
  const trimmed = candidate.replace(/\/$/, "");
  if (!trimmed) return "";
  try {
    const url = new URL(trimmed.startsWith("http") ? trimmed : `http://${trimmed}`);
    if (isLocalhostHost(url.hostname) && pageHost && !isLocalhostHost(pageHost)) {
      return "";
    }
    return trimmed.startsWith("http") ? trimmed : `http://${trimmed}`;
  } catch {
    return "";
  }
}

/** Clear stale dev override that points at 127.0.0.1 when browsing from another LAN host. */
export function sanitizeBridgeBaseOverride(): boolean {
  const pageHost = window.location.hostname;
  if (!pageHost || isLocalhostHost(pageHost)) return false;
  const override = localStorage.getItem(BRIDGE_OVERRIDE_KEY);
  if (!override?.trim()) return false;
  const resolved = resolveBase(override, pageHost);
  if (!resolved) {
    localStorage.removeItem(BRIDGE_OVERRIDE_KEY);
    return true;
  }
  return false;
}

export function getBridgeBase(): string {
  const pageHost = typeof window !== "undefined" ? window.location.hostname : "";
  const override = localStorage.getItem(BRIDGE_OVERRIDE_KEY);
  if (override?.trim()) {
    return resolveBase(override, pageHost);
  }
  const env = import.meta.env.VITE_DESKTOP_BRIDGE_BASE as string | undefined;
  if (env?.trim()) {
    return resolveBase(env, pageHost);
  }
  return "";
}

function shouldRedirectLogin(): boolean {
  const publicPaths = new Set(["/", "/login"]);
  return window.top === window.self && !publicPaths.has(window.location.pathname);
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
    signal: init?.signal,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) {
    sessionStorage.removeItem(TOKEN_KEY);
    if (shouldRedirectLogin()) {
      window.location.assign("/login");
    }
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    try {
      const body = JSON.parse(text) as { detail?: string | { error?: string; detail?: string; message?: string } };
      if (typeof body.detail === "string") {
        throw new Error(body.detail);
      }
      if (body.detail && typeof body.detail === "object") {
        const nested = body.detail;
        if (typeof nested.error === "string") throw new Error(nested.error);
        if (typeof nested.detail === "string") throw new Error(nested.detail);
        if (typeof nested.message === "string") throw new Error(nested.message);
        throw new Error(JSON.stringify(nested));
      }
    } catch (e) {
      if (e instanceof SyntaxError) {
        // not JSON — fall through to plain-text error
      } else if (e instanceof Error) {
        throw e;
      }
    }
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Download binary payloads (zip exports) with shared auth/base-url behavior. */
export async function apiDownloadBlob(
  path: string,
  init?: RequestInit,
): Promise<{ blob: Blob; filename: string }> {
  const base = getBridgeBase();
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) {
    sessionStorage.removeItem(TOKEN_KEY);
    if (shouldRedirectLogin()) {
      window.location.assign("/login");
    }
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    try {
      const body = JSON.parse(text) as { detail?: string };
      if (typeof body.detail === "string") throw new Error(body.detail);
    } catch (e) {
      if (e instanceof Error && e.message !== text) throw e;
    }
    throw new Error(text || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const dispo = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(dispo);
  const filename = match?.[1] || "download.zip";
  return { blob, filename };
}

/** Fetch non-JSON responses (e.g. TTL) with shared auth/base-url behavior. */
export async function apiFetchText(path: string, init?: RequestInit): Promise<string> {
  const base = getBridgeBase();
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) {
    sessionStorage.removeItem(TOKEN_KEY);
    if (shouldRedirectLogin()) {
      window.location.assign("/login");
    }
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.text();
}

export function setToken(token: string) {
  sessionStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event("ofdd-auth"));
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event("ofdd-auth"));
}

export function hasToken(): boolean {
  return Boolean(sessionStorage.getItem(TOKEN_KEY));
}

export type AuthStatus = { auth_required: boolean };

export async function fetchAuthStatus(): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/api/auth/status");
}

export type AuthMe = { username: string; role: string; auth_required: boolean };

export async function fetchAuthMe(): Promise<AuthMe> {
  return apiFetch<AuthMe>("/api/auth/me");
}

export async function login(username: string, password: string) {
  return apiFetch<{ token: string; username: string; role: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

/** Short-lived ticket for /ws/dashboard (not the long-lived Bearer token). */
export async function fetchWsTicket(): Promise<string | null> {
  try {
    const body = await apiFetch<{ ticket: string }>("/api/auth/ws-ticket", { method: "POST" });
    return body.ticket?.trim() || null;
  } catch {
    return null;
  }
}
