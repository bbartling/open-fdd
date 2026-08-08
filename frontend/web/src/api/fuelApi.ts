import { getStoredToken } from "./authApi";
import { ApiClientError, apiFetch, parseErrorEnvelope } from "./client";
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

export const FUEL_CAMPUS_IMPORT_PATH = "/api/fuel/campus/import";
export const FUEL_CAMPUS_LIST_PATH = "/api/fuel/campus";
export const FUEL_WEATHER_FETCH_PATH = "/api/fuel/campus/weather/fetch";
export const FUEL_ANALYTICS_PATH = "/api/analytics/fuel";

export const FUEL_QUERY_VERSIONS = [
  "fuel-summary-v1",
  "fuel-monthly-v1",
  "fuel-stacked-v1",
  "fuel-intensity-v1",
  "fuel-demand-v1",
  "fuel-quality-v1",
  "fuel-weather-v1",
] as const;

export type FuelQueryVersion = (typeof FUEL_QUERY_VERSIONS)[number];

export interface FuelCampusMeta {
  campus_id: string;
  label?: string;
  notes?: string;
  total_area_ft2?: number;
  error?: string;
  [key: string]: unknown;
}

export interface FuelCampusListResponse {
  ok?: boolean;
  fuel_root?: string;
  count?: number;
  campuses?: FuelCampusMeta[];
  active?: FuelCampusMeta | null;
  error?: string;
}

export interface FuelCampusImportResponse {
  ok: boolean;
  campus_id?: string;
  path?: string;
  campus?: FuelCampusMeta;
  error?: string;
  hint?: string;
}

export interface FuelAnalyticsRequest {
  query_version: FuelQueryVersion | string;
  campus_id?: string;
  allocation?: "area_weighted" | string;
  building_id?: string;
  gap_fill?: boolean;
}

export interface FuelAnalyticsEnvelope {
  ok?: boolean;
  schema_version?: string;
  query_version?: string;
  engine?: string;
  rows: Record<string, unknown>[];
  points?: Record<string, unknown>[];
  coverage?: Record<string, unknown> | null;
  warnings: string[];
  fits?: Record<string, unknown>[];
  summary?: Record<string, unknown>;
  campus_id?: string;
  error?: string;
  generated_at?: string;
}

/** Build multipart body for a fuel campus zip upload. */
export function buildFuelUploadFormData(file: File, fieldName = "file"): FormData {
  const form = new FormData();
  form.append(fieldName, file, file.name);
  return form;
}

/**
 * Upload a fuel campus zip via multipart POST.
 * Same auth / x-request-id pattern as package upload.
 */
export async function importFuelCampus(
  file: File,
): Promise<FuelCampusImportResponse> {
  const requestId = newRequestId();
  const token = getStoredToken();
  if (!token && typeof window !== "undefined") {
    const here = `${window.location.pathname}${window.location.search}`;
    window.location.assign(`/auth?from=${encodeURIComponent(here)}`);
    throw new ApiClientError("Login required before fuel campus import", {
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

  const res = await fetch(buildUrl(FUEL_CAMPUS_IMPORT_PATH), {
    method: "POST",
    headers,
    body: buildFuelUploadFormData(file),
  });

  const responseRequestId = res.headers.get(REQUEST_ID_HEADER) ?? requestId;
  const text = await res.text();

  let body: FuelCampusImportResponse;
  try {
    body = JSON.parse(text) as FuelCampusImportResponse;
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
      code: "fuel.upload.error",
      retryable: res.status >= 500,
      requestId: responseRequestId,
      status: res.status,
    });
  }

  if (!body.ok) {
    throw new ApiClientError(body.error ?? "Fuel campus import failed", {
      code: "fuel.upload.rejected",
      retryable: false,
      requestId: responseRequestId,
      status: res.status,
    });
  }

  return body;
}

export async function listFuelCampuses(): Promise<FuelCampusListResponse> {
  return apiFetch<FuelCampusListResponse>(FUEL_CAMPUS_LIST_PATH);
}

function emptyFuelEnvelope(queryVersion: string): FuelAnalyticsEnvelope {
  return {
    ok: false,
    schema_version: "",
    query_version: queryVersion,
    engine: "",
    rows: [],
    points: [],
    warnings: [],
  };
}

/** Normalize fuel analytics response into a usable envelope. */
export function unwrapFuelEnvelope(
  body: FuelAnalyticsEnvelope | null | undefined,
  fallbackQuery = "",
): FuelAnalyticsEnvelope {
  if (!body || typeof body !== "object") {
    return emptyFuelEnvelope(fallbackQuery);
  }
  return {
    ok: body.ok,
    schema_version: body.schema_version != null ? String(body.schema_version) : "",
    query_version: body.query_version != null ? String(body.query_version) : fallbackQuery,
    engine: body.engine != null ? String(body.engine) : "",
    rows: Array.isArray(body.rows) ? body.rows : [],
    points: Array.isArray(body.points) ? body.points : [],
    coverage: body.coverage ?? null,
    warnings: Array.isArray(body.warnings) ? body.warnings : [],
    fits: Array.isArray(body.fits) ? body.fits : undefined,
    summary:
      body.summary && typeof body.summary === "object" ? body.summary : undefined,
    campus_id: body.campus_id != null ? String(body.campus_id) : undefined,
    error: body.error,
    generated_at: body.generated_at,
  };
}

export async function postFuelAnalytics(
  body: FuelAnalyticsRequest,
): Promise<FuelAnalyticsEnvelope> {
  const raw = await apiFetch<{
    ok?: boolean;
    analytics?: FuelAnalyticsEnvelope;
    error?: string;
  } & FuelAnalyticsEnvelope>(FUEL_ANALYTICS_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const inner =
    raw && typeof raw === "object" && raw.analytics && typeof raw.analytics === "object"
      ? raw.analytics
      : raw;
  const env = unwrapFuelEnvelope(inner, body.query_version);
  if (env.ok === false && (env.error || (env.warnings?.length ?? 0) > 0)) {
    const msg = env.error || env.warnings[0] || "Fuel analytics failed";
    if (env.rows.length === 0 && (env.points?.length ?? 0) === 0) {
      throw new Error(msg);
    }
  }
  return env;
}

export interface FuelOpenMeteoFetchResponse {
  ok: boolean;
  campus_id?: string;
  source?: string;
  path?: string;
  months?: number;
  start_date?: string;
  end_date?: string;
  downloaded_at_utc?: string;
  lat?: number;
  lon?: number;
  hint?: string;
  error?: string;
  action_id?: string;
}

/** vibe20 “Fetch Open-Meteo” — archive HDD/CDD for fuel weather baseline. */
export async function fetchFuelOpenMeteo(
  campusId: string,
): Promise<FuelOpenMeteoFetchResponse> {
  return apiFetch<FuelOpenMeteoFetchResponse>(FUEL_WEATHER_FETCH_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ campus_id: campusId }),
  });
}
