import { getStoredToken } from "./authApi";
import { ApiClientError, parseErrorEnvelope } from "./client";
import { newRequestId } from "./requestId";

const REQUEST_ID_HEADER = "x-request-id";

function apiBase(): string {
  const base = import.meta.env.VITE_API_BASE ?? "";
  return base.replace(/\/$/, "");
}

function buildUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const base = apiBase();
  return base ? `${base}${normalized}` : normalized;
}

export interface PackageEquipmentReport {
  equipment_id: string;
  column_count?: number;
  roles?: Record<string, string>;
  unmapped_columns?: string[];
  map_source?: string;
}

export interface PackageImportResponse {
  ok: boolean;
  error?: string;
  hint?: string;
  /** Registered dataset id (same as building_id from manifest). */
  building_id?: string;
  schema_version?: string;
  grid_minutes?: number;
  poll_seconds?: number;
  timezone?: string | null;
  equipment?: PackageEquipmentReport[];
  equipment_written?: number;
  total_rows?: number;
  total_ms?: number;
  package_root?: string;
  warnings?: string[];
  missing_maps?: string[];
}

export const PACKAGE_IMPORT_PATH = "/api/csv/import/package";

/** Build multipart body for a single package zip upload. */
export function buildPackageUploadFormData(file: File, fieldName = "file"): FormData {
  const form = new FormData();
  form.append(fieldName, file, file.name);
  return form;
}

/**
 * Upload an `openfdd_package_v1` zip via multipart POST.
 * Central accepts multipart, JSON base64, or raw zip — React uses multipart only.
 */
export async function uploadPackage(file: File): Promise<PackageImportResponse> {
  const requestId = newRequestId();
  const token = getStoredToken();
  if (!token && typeof window !== "undefined") {
    const here = `${window.location.pathname}${window.location.search}`;
    window.location.assign(`/auth?from=${encodeURIComponent(here)}`);
    throw new ApiClientError("Login required before package upload", {
      code: "auth.required",
      retryable: false,
      requestId,
      status: 401,
    });
  }
  const headers: Record<string, string> = {
    Accept: "application/json",
    [REQUEST_ID_HEADER]: requestId,
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(buildUrl(PACKAGE_IMPORT_PATH), {
    method: "POST",
    headers,
    body: buildPackageUploadFormData(file),
  });

  const responseRequestId = res.headers.get(REQUEST_ID_HEADER) ?? requestId;
  const text = await res.text();

  let body: PackageImportResponse;
  try {
    body = JSON.parse(text) as PackageImportResponse;
  } catch {
    throw new ApiClientError(text || `HTTP ${res.status}`, {
      code: "http.error",
      retryable: res.status >= 500,
      requestId: responseRequestId,
      status: res.status,
    });
  }

  if (!res.ok) {
    const envelope = parseErrorEnvelope(text);
    if (envelope) {
      throw new ApiClientError(envelope.error.message, {
        code: envelope.error.code,
        retryable: envelope.error.retryable,
        requestId: envelope.error.request_id || responseRequestId,
        status: res.status,
      });
    }
    throw new ApiClientError(body.error ?? text ?? `HTTP ${res.status}`, {
      code: "upload.error",
      retryable: res.status >= 500,
      requestId: responseRequestId,
      status: res.status,
    });
  }

  if (!body.ok) {
    throw new ApiClientError(body.error ?? "Package import failed", {
      code: "upload.rejected",
      retryable: false,
      requestId: responseRequestId,
      status: res.status,
    });
  }

  return body;
}

/** Dataset registry id returned on successful package ingest. */
export function packageDatasetId(response: PackageImportResponse): string | undefined {
  return response.building_id;
}
