/** Load agent / UT3 import session into client fusion preview (before Feather save). */

import { apiFetch } from "./api";
import { datasetsToCsv, type CsvDataset } from "./csvWorkbench";

export type FusionPreviewResponse = {
  ok?: boolean;
  error?: string;
  session_id?: string;
  dataset_name?: string;
  row_count?: number;
  preview_row_count?: number;
  truncated?: boolean;
  columns?: string[];
  rows?: string[][];
  validation_report?: { warnings?: string[] };
  fusion_url_hint?: string;
};

export async function fetchAgentSessionFusionPreview(
  sessionId: string,
  limit = 2000,
): Promise<FusionPreviewResponse> {
  return apiFetch<FusionPreviewResponse>(
    `/api/csv/import/sessions/${encodeURIComponent(sessionId)}/fusion-preview?limit=${limit}`,
  );
}

export function datasetFromFusionPreview(
  data: FusionPreviewResponse,
  sessionId: string,
): CsvDataset {
  const columns = data.columns ?? [];
  const allRows = data.rows ?? [];
  const name = `${data.dataset_name ?? "agent-cleaned"}-${sessionId.slice(0, 8)}.csv`;
  const fullText = datasetsToCsv(columns, allRows);
  const tsCol =
    columns.find((c) => c === "ts_local" || c === "Date" || c.toLowerCase().includes("date")) ??
    columns[0] ??
    null;
  return {
    id: `agent-${sessionId}`,
    name,
    columns,
    rows: allRows.slice(0, 500),
    allRows,
    rowCount: data.row_count ?? allRows.length,
    bytes: fullText.length,
    timestampColumn: tsCol,
    fullText,
  };
}

export async function fetchLatestPlannedSession(): Promise<{
  ok?: boolean;
  session_id?: string;
  fusion_url?: string;
  session?: Record<string, unknown>;
  error?: string;
}> {
  return apiFetch("/api/csv/import/sessions/latest/planned");
}

export async function saveAgentSessionToArrow(
  sessionId: string,
): Promise<{
  ok?: boolean;
  error?: string;
  dataset?: { id?: string };
  historian_sync?: {
    ok?: boolean;
    site_id?: string;
    equipment_id?: string;
    plot_url?: string;
    model_url?: string;
    rows_synced?: number;
  };
}> {
  return apiFetch("/api/csv/import/execute", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, confirm: true }),
  });
}
