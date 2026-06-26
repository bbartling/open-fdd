/** Shapes from GET /api/dashboard/summary and /api/dashboard/analytics */

export type DashboardSummary = {
  ok?: boolean;
  model_coverage?: {
    equipment_count?: number;
    point_count?: number;
    mapped_points?: number;
    unmapped_points?: number;
    model_score?: number | null;
    query_engine?: string;
  };
  source_health?: {
    sources?: Array<{
      protocol?: string;
      enabled?: boolean;
      status?: string;
      point_count?: number;
    }>;
  };
  historian_health?: {
    row_count?: number;
    latest_sample_at?: string;
    subdir_count?: number;
    storage_label?: string;
  };
  faults?: {
    active_count?: number;
    total_count?: number;
    confirmed_count?: number;
  };
  validation?: {
    profile_id?: string;
    live_fdd_pass?: string;
  };
};

export type DashboardAnalytics = {
  ok?: boolean;
  rule_health?: {
    rule_count?: number;
    datafusion_ok?: boolean;
    last_error?: string | null;
  };
  source_coverage?: {
    protocols?: Array<{ protocol?: string; point_count?: number }>;
  };
};

export type FddRulesResponse = {
  ok?: boolean;
  rules?: Array<{ id?: string; name?: string; enabled?: boolean }>;
};
