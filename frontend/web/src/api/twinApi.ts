import { apiFetch, ApiClientError } from "./client";

export type UnityBuildStatus = {
  ok: boolean;
  webgl_root?: string;
  zip_sha256?: string | null;
  twin_version_id?: string;
  unity_build_id?: string;
  error?: string;
};

export type V1ModelsResponse = Record<string, unknown>;

export const UNITY_ACTIVE_PATH = "/api/unity/builds/active";
export const V1_MODELS_PATH = "/api/v1/models";
export const V1_HEALTH_PATH = "/api/v1/health";
/** Multipart import endpoints (central vibe21); may be SCAFFOLD until wired. */
export const UNITY_IMPORT_PATH = "/api/unity/builds/import";
export const MODEL_RELEASE_IMPORT_PATH = "/api/v1/models/import";
export const TRAINING_EXPORT_PATH = "/api/v1/training/export";

export function rejectJoblibName(name: string): string | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".joblib") || lower.endsWith(".pkl") || lower.endsWith(".pickle")) {
    return "joblib/pickle uploads are forbidden online — use model_release.zip";
  }
  return null;
}

export async function fetchUnityActive(): Promise<UnityBuildStatus> {
  return apiFetch<UnityBuildStatus>(UNITY_ACTIVE_PATH);
}

export async function fetchV1Models(): Promise<V1ModelsResponse> {
  return apiFetch<V1ModelsResponse>(V1_MODELS_PATH);
}

export async function fetchV1Health(): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(V1_HEALTH_PATH);
}

function clientReject(code: string, message: string): never {
  throw new ApiClientError(message, {
    code,
    retryable: false,
    requestId: "client",
    status: 400,
  });
}

/** Raw zip body — binary-safe (multipart UTF-8 parsers corrupt archives). */
async function postZip(
  path: string,
  file: File,
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/zip",
      "X-Filename": file.name,
    },
    body: file,
  });
}

export async function importUnityZip(file: File): Promise<Record<string, unknown>> {
  const bad = rejectJoblibName(file.name);
  if (bad) clientReject("twin.reject_joblib", bad);
  if (!file.name.toLowerCase().endsWith(".zip")) {
    clientReject("twin.expect_zip", "Choose a .zip Unity WebGL build");
  }
  return postZip(UNITY_IMPORT_PATH, file);
}

export async function importModelReleaseZip(file: File): Promise<Record<string, unknown>> {
  const bad = rejectJoblibName(file.name);
  if (bad) clientReject("twin.reject_joblib", bad);
  if (!file.name.toLowerCase().endsWith(".zip")) {
    clientReject("twin.expect_zip", "Choose model_release.zip");
  }
  return postZip(MODEL_RELEASE_IMPORT_PATH, file);
}
