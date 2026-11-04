import { apiFetch } from "./client";

export interface DeleteDatasetResponse {
  ok: boolean;
  error?: string;
  action_id?: string;
}

/** Purge site ≡ dataset: registry + csv_buildings + feathers + parquet + rule_results (+ jobs via central). */
export async function deleteDataset(
  datasetId: string,
): Promise<DeleteDatasetResponse> {
  const id = datasetId.trim();
  if (!id) {
    throw new Error("site id required");
  }
  return apiFetch<DeleteDatasetResponse>(
    `/api/datasets?id=${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}
