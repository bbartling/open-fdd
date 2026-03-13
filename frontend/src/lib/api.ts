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

async function readErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";

  try {
    if (contentType.includes("application/json")) {
      const payload = (await response.json()) as {
        detail?: string | { msg?: string }[];
        error?: string;
        message?: string;
      };
      if (typeof payload.detail === "string") return payload.detail;
      if (Array.isArray(payload.detail)) {
        return payload.detail.map((item) => item.msg ?? "Validation error").join("; ");
      }
      if (payload.error) return payload.error;
      if (payload.message) return payload.message;
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