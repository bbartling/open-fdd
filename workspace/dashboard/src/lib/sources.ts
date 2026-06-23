export type SourceHealth = {
  status?: string;
  message?: string;
  last_error?: string | null;
};

export type SourceRecord = {
  source_id: string;
  source_type: string;
  display_name: string;
  enabled?: boolean;
  site_id?: string;
  building_id?: string;
  config_path?: string;
  health?: SourceHealth;
  last_poll_at?: string | null;
  last_backfill_at?: string | null;
  row_count?: number;
  mapped_points?: number;
  unmapped_points?: number;
};

export type BackfillJob = {
  job_id: string;
  source_id: string;
  status?: string;
  rows_written?: number;
  rows_read?: number;
  started_at?: string;
  completed_at?: string | null;
};

export const SOURCES_PANEL_TITLE = "Data Connectors";

export function healthTone(status?: string): "ok" | "warn" | "bad" | "muted" {
  switch ((status || "").toLowerCase()) {
    case "online":
      return "ok";
    case "degraded":
      return "warn";
    case "offline":
      return "bad";
    default:
      return "muted";
  }
}

export function canMutateSources(role: string | null): boolean {
  return role === "integrator" || role === "agent";
}

export function formatSourceType(sourceType: string): string {
  return sourceType.replace(/_/g, " ");
}
