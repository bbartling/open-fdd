import { apiFetch, apiUploadForm } from "./api";

export type CsvPreviewFileProfile = {
  filename: string;
  profile?: {
    row_count?: number;
    delimiter?: string;
    encoding?: string;
    headers?: string[];
    timestamp_candidates?: [number, number][];
    columns?: { original_name: string; kind: string }[];
  };
  error?: string;
};

export type CsvPreviewResponse = {
  session_id?: string;
  files?: CsvPreviewFileProfile[];
  ok?: boolean;
  error?: string;
  errors?: { file?: string; error?: string }[];
};

const SMALL_UPLOAD_MAX_BYTES = 900_000;

async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]!);
  return btoa(binary);
}

/** Upload CSV files to UT3 preview API (multipart or JSON base64). */
export async function uploadFilesForPreview(
  fileList: FileList | File[],
  existingSessionId?: string,
): Promise<CsvPreviewResponse> {
  const files = Array.from(fileList);
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
  if (totalBytes <= SMALL_UPLOAD_MAX_BYTES) {
    const payload = await Promise.all(
      files.map(async (f) => ({
        filename: f.name,
        content_base64: await fileToBase64(f),
      })),
    );
    return apiFetch<CsvPreviewResponse>("/api/csv/import/preview", {
      method: "POST",
      body: JSON.stringify({ session_id: existingSessionId || undefined, files: payload }),
    });
  }
  const form = new FormData();
  for (const f of files) form.append("file", f, f.name);
  if (existingSessionId) form.append("session_id", existingSessionId);
  return apiUploadForm<CsvPreviewResponse>("/api/csv/import/preview", form);
}
