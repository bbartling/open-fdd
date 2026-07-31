import type { ApiErrorEnvelope } from "./contract";

const REQUEST_ID_HEADER = "x-request-id";

function newRequestId(): string {
  return crypto.randomUUID();
}

export class ApiClientError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId: string;
  readonly status: number;

  constructor(
    message: string,
    opts: { code: string; retryable: boolean; requestId: string; status: number },
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = opts.code;
    this.retryable = opts.retryable;
    this.requestId = opts.requestId;
    this.status = opts.status;
  }
}

/** Parse the standard error envelope; returns null if body is not an envelope. */
export function parseErrorEnvelope(text: string): ApiErrorEnvelope | null {
  try {
    const body = JSON.parse(text) as unknown;
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      body.error &&
      typeof body.error === "object" &&
      "code" in body.error &&
      "message" in body.error
    ) {
      return body as ApiErrorEnvelope;
    }
  } catch {
    // not JSON
  }
  return null;
}

function apiBase(): string {
  const base = import.meta.env.VITE_API_BASE ?? "";
  return base.replace(/\/$/, "");
}

function buildUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const base = apiBase();
  return base ? `${base}${normalized}` : normalized;
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const requestId = newRequestId();
  const res = await fetch(buildUrl(path), {
    ...init,
    headers: {
      Accept: "application/json",
      [REQUEST_ID_HEADER]: requestId,
      ...(init?.headers ?? {}),
    },
  });

  const responseRequestId =
    res.headers.get(REQUEST_ID_HEADER) ?? requestId;

  if (!res.ok) {
    const text = await res.text();
    const envelope = parseErrorEnvelope(text);
    if (envelope) {
      throw new ApiClientError(envelope.error.message, {
        code: envelope.error.code,
        retryable: envelope.error.retryable,
        requestId: envelope.error.request_id || responseRequestId,
        status: res.status,
      });
    }
    throw new ApiClientError(text || `HTTP ${res.status}`, {
      code: "http.error",
      retryable: res.status >= 500,
      requestId: responseRequestId,
      status: res.status,
    });
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const text = await res.text();
    return text as T;
  }

  return res.json() as Promise<T>;
}
