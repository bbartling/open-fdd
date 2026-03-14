const apiKey = import.meta.env.VITE_OFDD_API_KEY as string | undefined;

function buildHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init ?? {});
  if (apiKey && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${apiKey}`);
  }
  return headers;
}

function buildUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return path.startsWith("/") ? path : `/${path}`;
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
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: buildHeaders(init?.headers),
  });

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
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: buildHeaders(init?.headers),
  });

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(`${response.status} ${message}`.trim());
  }

  return response.text();
}

export async function apiFetchBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: buildHeaders(init?.headers),
  });

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(`${response.status} ${message}`.trim());
  }

  return response.blob();
}