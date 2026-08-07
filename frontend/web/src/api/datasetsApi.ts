import { apiFetch } from "./client";

export interface DeleteDatasetResponse {
  ok: boolean;
  error?: string;
  action_id?: string;
}

/** Purge registry + csv_buildings + feather package/csv + parquet + rule_results. */
export async function deleteDataset(
  datasetId: string,
): Promise<DeleteDatasetResponse> {
  const id = datasetId.trim();
  if (!id) {
    throw new Error("dataset id required");
  }
  return apiFetch<DeleteDatasetResponse>(
    `/api/datasets?id=${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}
