import { apiFetch, apiUploadForm } from "./api";
import type { ColumnMapDocument } from "./columnMap";

export type ZipMappingStatus = {
  present?: boolean;
  valid?: boolean;
  errors?: string[];
  raw_present?: boolean;
};

export type ZipPackageManifest = {
  ok?: boolean;
  error?: string;
  package_id?: string;
  filename?: string;
  status?: string;
  zip_bytes?: number;
  entry_count?: number;
  file_count?: number;
  csv_files?: string[];
  json_files?: string[];
  weather_csvs?: string[];
  equipment?: Record<string, string[]>;
  package_manifest?: Record<string, unknown> | null;
  column_map?: ColumnMapDocument | null;
  mapping_status?: ZipMappingStatus;
  session_config?: Record<string, unknown> | null;
};

export type ZipPlanResponse = {
  ok?: boolean;
  error?: string;
  package_id?: string;
  session_id?: string;
  files?: { filename?: string; package_path?: string; error?: string; profile?: { headers?: string[]; row_count?: number } }[];
  errors?: { file?: string; error?: string }[];
  mapping_applied?: boolean;
  mapping_errors?: string[];
  column_map?: ColumnMapDocument | null;
  hint?: string;
};

const SMALL_UPLOAD_MAX_BYTES = 900_000;

async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]!);
  return btoa(binary);
}

/** Upload + safe-inspect a ZIP package (returns package manifest). */
export async function inspectZipPackage(file: File): Promise<ZipPackageManifest> {
  if (file.size <= SMALL_UPLOAD_MAX_BYTES) {
    return apiFetch<ZipPackageManifest>("/api/csv/import/zip/inspect", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_base64: await fileToBase64(file),
      }),
    });
  }
  const form = new FormData();
  form.append("file", file, file.name);
  return apiUploadForm<ZipPackageManifest>("/api/csv/import/zip/inspect", form);
}

/** Stage package CSVs into an import session and draft a plan. */
export async function planZipPackage(packageId: string): Promise<ZipPlanResponse> {
  return apiFetch<ZipPlanResponse>("/api/csv/import/zip/plan", {
    method: "POST",
    body: JSON.stringify({ package_id: packageId }),
  });
}

export function summarizeZipManifest(m: ZipPackageManifest): string {
  const csvs = m.csv_files?.length ?? 0;
  const equip = m.equipment ? Object.keys(m.equipment).length : 0;
  const map = m.mapping_status?.valid
    ? "mapping valid"
    : m.mapping_status?.present
      ? "mapping present (needs review)"
      : "mapping missing";
  return `${csvs} CSV · ${equip} equipment folder(s) · ${map}`;
}
