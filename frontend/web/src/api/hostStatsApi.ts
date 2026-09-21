import { apiFetch } from "./client";

export type HostMemoryStats = {
  available?: boolean;
  source?: string;
  used_bytes?: number | null;
  total_bytes?: number | null;
  available_bytes?: number | null;
  percent_used?: number | null;
  note?: string;
};

export type HostStorageStats = {
  available?: boolean;
  path?: string;
  used_bytes?: number | null;
  total_bytes?: number | null;
  available_bytes?: number | null;
  percent_used?: number | null;
  source?: string;
};

export type HostParquetStats = {
  available?: boolean;
  file_count?: number;
  small_file_count?: number;
  estimated_bytes?: number;
  target_file_mb?: number;
  compaction_status?: string;
  note?: string;
};

export type CompactionCoordinatorStatus = {
  mode?: string;
  scanners?: number;
  compacting?: boolean;
};

export type HostStatsResponse = {
  ok?: boolean;
  memory?: HostMemoryStats;
  storage?: HostStorageStats;
  data_management?: {
    parquet?: HostParquetStats;
  };
  compaction_coordinator?: CompactionCoordinatorStatus;
};

export type HistorianCompactionResponse = {
  ok?: boolean;
  error?: string;
  plan_only?: boolean;
  plans?: unknown;
  results?: unknown;
  summary?: {
    partitions?: number;
    input_files?: number;
    output_files?: number;
    rows?: number;
    cleanup_pending_files?: number;
  };
  coordinator?: CompactionCoordinatorStatus;
  historian?: {
    parquet_files?: number;
    small_files?: number;
    rows?: number;
  };
};

export async function getHostStats(): Promise<HostStatsResponse> {
  return apiFetch<HostStatsResponse>("/api/host/stats");
}

export async function getHistorianCompactionStatus(): Promise<HistorianCompactionResponse> {
  return apiFetch<HistorianCompactionResponse>("/api/historian/compaction");
}

export async function runHistorianCompaction(opts: {
  confirm: boolean;
  wait?: boolean;
  plan_only?: boolean;
}): Promise<HistorianCompactionResponse> {
  return apiFetch<HistorianCompactionResponse>("/api/historian/compaction", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
}

export function formatBytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"] as const;
  let n = value;
  let u = 0;
  while (n >= 1024 && u < units.length - 1) {
    n /= 1024;
    u += 1;
  }
  return `${n.toFixed(u === 0 ? 0 : 1)} ${units[u]}`;
}
