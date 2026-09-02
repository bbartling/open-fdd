import { getStoredToken } from "./authApi";
import { ApiClientError, apiFetch, parseErrorEnvelope } from "./client";
import { newRequestId } from "./requestId";

const REQUEST_ID_HEADER = "x-request-id";

export type ExportProfile = "summary" | "diagnostic" | "forensic";

export interface EngineeringExport {
  export_id: string;
  job_id: string;
  building_id: string;
  profile: ExportProfile;
  filename: string;
  download_url: string;
  schema_version?: string;
  created_at?: string;
  size_bytes?: number;
}

interface CreateExportResponse {
  ok: boolean;
  export: EngineeringExport;
}

function apiUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${normalized}` : normalized;
}

function exportPath(jobId: string, suffix = ""): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/exports${suffix}`;
}

export async function createExport(
  jobId: string,
  buildingId: string,
  profile: ExportProfile = "summary",
): Promise<EngineeringExport> {
  const body = await apiFetch<CreateExportResponse>(exportPath(jobId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ building_id: buildingId, profile }),
  });
  return body.export;
}

export async function downloadExport(
  jobId: string,
  exportId: string,
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
    apiUrl(exportPath(jobId, `/${encodeURIComponent(exportId)}/download`)),
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
      code: envelope?.error.code ?? "export.download_error",
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
