import { desktopFetch } from "./api";

export function uploadRule(filename: string, content: string) {
  return desktopFetch<{ filename: string; size: number }>("/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, content }),
  });
}

export function deleteRule(filename: string) {
  return desktopFetch<{ deleted: string }>(`/rules/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export function syncRuleDefinitions() {
  return desktopFetch<{ synced: number; mode: string }>("/rules/sync-definitions", {
    method: "POST",
  });
}

export function purgeTimeseries(siteId?: string, prunePoints = false) {
  return desktopFetch<{
    files_deleted: number;
    dirs_deleted: number;
    bytes_deleted: number;
    points_removed: number;
    ttl_sync_warning?: string;
  }>("/storage/timeseries/purge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: null,
      site_id: siteId ?? null,
      prune_points: prunePoints,
    }),
  });
}
