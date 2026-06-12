/** Analytics + RCx report API client (read-only). */

import { apiFetch, getBridgeBase } from "./api";

function authHeaders(): HeadersInit {
  const token = sessionStorage.getItem("ofdd_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type OverviewResponse = {
  site_name: string;
  kpis: {
    active_faults: number;
    critical_high_faults: number;
    total_fault_hours: number;
    online_edge_instances: number;
    bacnet_stale_points: number;
    model_warnings: number;
    equipment_with_faults: number;
    validation_status: string;
  };
  faults_by_severity: { group: string; elapsed_hours: number }[];
  fault_hours_by_equipment: { group: string; elapsed_hours: number; equipment_type?: string }[];
  fault_hours_by_code: { group: string; elapsed_hours: number }[];
  top_faults: {
    equipment: string;
    equipment_type: string;
    fault_name: string;
    severity: string;
    elapsed_fault_hours: number;
    samples_flagged: number;
    samples_evaluated: number;
    recommended_next_step: string;
  }[];
};

export type RcxPreviewResponse = {
  site: string;
  site_name: string;
  window: { start: string | null; end: string | null; hours: number };
  available_charts: { id: string; label: string }[];
  disabled_charts: { id: string; label: string; reason: string }[];
  sections: { id: string; label: string }[];
  warnings: string[];
  fault_summary: { active_faults: number; total_fault_hours: number };
  fault_rows: unknown[];
};

export async function fetchAnalyticsOverview(): Promise<OverviewResponse> {
  return apiFetch("/api/analytics/overview");
}

export async function fetchFaultAnalytics(hours = 24): Promise<Record<string, unknown>> {
  return apiFetch(`/api/analytics/faults?hours=${hours}`);
}

export async function fetchModelHealth(): Promise<Record<string, unknown>> {
  return apiFetch("/api/analytics/model-health");
}

export async function fetchRcxPreview(body: {
  site_id?: string;
  hours?: number;
  scope?: string;
}): Promise<RcxPreviewResponse> {
  return apiFetch("/api/reports/rcx/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function downloadRcxReport(body: {
  site_id?: string;
  hours?: number;
  scope?: string;
  sections?: string[];
  charts?: string[];
}): Promise<Blob> {
  const res = await fetch(`${getBridgeBase()}/api/reports/rcx/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Report failed (${res.status})`);
  }
  return res.blob();
}
