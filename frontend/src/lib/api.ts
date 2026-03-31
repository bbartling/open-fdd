import {
  clearAuthTokens,
  getAccessToken,
  setAccessToken,
} from "@/lib/auth";

let refreshPromise: Promise<string | null> | null = null;
/** Avoid dozens of parallel 403s each scheduling a full page navigation. */
let loginRedirectScheduled = false;

function scheduleLoginRedirect(): void {
  if (typeof window === "undefined" || loginRedirectScheduled) return;
  const path = window.location.pathname;
  if (path === "/login" || path === "/logout") return;
  loginRedirectScheduled = true;
  window.location.assign("/login");
}
const apiBase = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(
  /\/$/,
  "",
);

function buildHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init ?? {});
  const accessToken = getAccessToken();
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return headers;
}

function buildUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return apiBase ? `${apiBase}${normalized}` : normalized;
}

function stringifyUnknown(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value.map((item) => stringifyUnknown(item)).filter(Boolean);
    return parts.join("; ");
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const preferred = [obj.msg, obj.message, obj.detail, obj.error]
      .map((item) => stringifyUnknown(item))
      .find(Boolean);
    if (preferred) return preferred;
    try {
      return JSON.stringify(obj);
    } catch {
      return String(obj);
    }
  }
  return String(value);
}

async function readErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";

  try {
    if (contentType.includes("application/json")) {
      const payload = (await response.json()) as {
        detail?: unknown;
        error?: unknown;
        message?: unknown;
      };
      const detailText = stringifyUnknown(payload.detail);
      if (detailText) return detailText;
      const errorText = stringifyUnknown(payload.error);
      if (errorText) return errorText;
      const messageText = stringifyUnknown(payload.message);
      if (messageText) return messageText;
    }

    const text = await response.text();
    if (text.trim()) return text.trim();
  } catch {
    // Fall through to generic status text.
  }

  return response.statusText || `HTTP ${response.status}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithAuthRetry(() =>
    fetch(buildUrl(path), {
      ...init,
      headers: buildHeaders(init?.headers),
    }),
  );

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(`${response.status} ${message}`.trim());
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function apiFetchText(path: string, init?: RequestInit): Promise<string> {
  const response = await fetchWithAuthRetry(() =>
    fetch(buildUrl(path), {
      ...init,
      headers: buildHeaders(init?.headers),
    }),
  );

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(`${response.status} ${message}`.trim());
  }

  return response.text();
}

/** Read a streaming text/plain (or chunked) response; calls onChunk for each decoded piece. */
export async function apiStreamText(
  path: string,
  onChunk: (text: string) => void,
  signal: AbortSignal,
  init?: Omit<RequestInit, "signal">,
): Promise<void> {
  const response = await fetchWithAuthRetry(() =>
    fetch(buildUrl(path), {
      ...init,
      headers: buildHeaders(init?.headers),
      signal,
    }),
  );

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(`${response.status} ${message}`.trim());
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }

  const decoder = new TextDecoder();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value?.length) {
        onChunk(decoder.decode(value, { stream: true }));
      }
    }
    const tail = decoder.decode();
    if (tail) onChunk(tail);
  } finally {
    reader.releaseLock();
  }
}

export async function apiFetchBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetchWithAuthRetry(() =>
    fetch(buildUrl(path), {
      ...init,
      headers: buildHeaders(init?.headers),
    }),
  );

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(`${response.status} ${message}`.trim());
  }

  return response.blob();
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const resp = await fetch(buildUrl("/auth/refresh"), {
        method: "POST",
        credentials: "include",
      });
      if (!resp.ok) {
        clearAuthTokens();
        return null;
      }
      const body = (await resp.json()) as { access_token?: string };
      if (!body.access_token) {
        clearAuthTokens();
        return null;
      }
      setAccessToken(body.access_token);
      return body.access_token;
    } catch {
      clearAuthTokens();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

/**
 * API middleware returns 401 only when the Authorization header is missing.
 * Expired or otherwise invalid JWTs still send Bearer ... but fail validation → 403 "Invalid auth token".
 * Without handling 403, the UI never calls /auth/refresh and BACnet (and other) calls look stuck on 403.
 */
async function responseIndicatesAuthRetryable(response: Response): Promise<boolean> {
  if (response.status === 401) {
    return true;
  }
  if (response.status !== 403) {
    return false;
  }
  const ct = response.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) {
    return false;
  }
  try {
    const payload = (await response.clone().json()) as {
      error?: { message?: string; code?: string };
    };
    const msg = String(payload.error?.message ?? "").trim();
    return msg === "Invalid auth token";
  } catch {
    return false;
  }
}

async function fetchWithAuthRetry(run: () => Promise<Response>): Promise<Response> {
  let response = await run();
  if (!getAccessToken()) {
    return response;
  }
  if (!(await responseIndicatesAuthRetryable(response))) {
    return response;
  }
  const refreshed = await refreshAccessToken();
  if (!refreshed) {
    // Refresh failed (e.g. API restarted → in-memory refresh store empty). Tokens were cleared;
    // force navigation so we are not stuck inside RequireAuth with a blank shell of errors.
    scheduleLoginRedirect();
    return response;
  }
  response = await run();
  return response;
}