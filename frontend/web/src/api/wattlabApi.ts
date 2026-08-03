import { getStoredToken } from "./authApi";
import { ApiClientError, apiFetch, parseErrorEnvelope } from "./client";
import { newRequestId } from "./requestId";

const REQUEST_ID_HEADER = "x-request-id";

export type WattlabDumpProfile = "summary" | "diagnostic" | "forensic";

export interface WattlabDump {
  dump_id: string;
  job_id: string;
  building_id: string;
  profile: WattlabDumpProfile;
  filename: string;
  download_url: string;
  created_at?: string;
  size_bytes?: number;
}

interface CreateDumpResponse {
  ok: boolean;
  dump: WattlabDump;
}

function apiUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${normalized}` : normalized;
}

function dumpPath(jobId: string, suffix = ""): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/wattlab/dumps${suffix}`;
}

export async function createDump(
  jobId: string,
  buildingId: string,
  profile: WattlabDumpProfile = "summary",
): Promise<WattlabDump> {
  const body = await apiFetch<CreateDumpResponse>(dumpPath(jobId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ building_id: buildingId, profile }),
  });
  return body.dump;
}

export async function downloadDump(
  jobId: string,
  dumpId: string,
  filename: string,
): Promise<void> {
  const requestId = newRequestId();
  const token = getStoredToken();
  const headers: Record<string, string> = {
    Accept: "application/zip",
    [REQUEST_ID_HEADER]: requestId,
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(
    apiUrl(
      dumpPath(jobId, `/${encodeURIComponent(dumpId)}/download`),
    ),
    { headers },
  );
  if (!response.ok) {
    const text = await response.text();
    const envelope = parseErrorEnvelope(text);
    let message = text || `HTTP ${response.status}`;
    if (!envelope) {
      try {
        const body = JSON.parse(text) as { error?: string };
        if (body.error) message = body.error;
      } catch {
        // Keep raw response text.
      }
    }
    throw new ApiClientError(envelope?.error.message ?? message, {
      code: envelope?.error.code ?? "wattlab.download_error",
      retryable: envelope?.error.retryable ?? response.status >= 500,
      requestId:
        envelope?.error.request_id ??
        response.headers.get(REQUEST_ID_HEADER) ??
        requestId,
      status: response.status,
    });
  }

  const objectUrl = URL.createObjectURL(await response.blob());
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
