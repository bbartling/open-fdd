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
  fault_hours_by_code: { group: string; label?: string; code?: string; elapsed_hours: number }[];
  active_fault_devices?: {
    equipment: string;
    equipment_type?: string;
    symptoms: string[];
    fault_codes: string[];
    elapsed_hours: number;
    samples_flagged?: number;
  }[];
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

export type RcxChartOption = {
  chart_id: string;
  title: string;
  equipment_id?: string;
  equipment_type?: string;
  partial_note?: string;
};

export type RcxBundle = {
  bundle_id: string;
  family: string;
  label: string;
  equipment_id?: string | null;
  equipment_name?: string | null;
  chart_ids: string[];
  chart_count: number;
  default_selected?: boolean;
};

export type RcxPreviewResponse = {
  site_id: string;
  site: string;
  site_name: string;
  window: { start: string | null; end: string | null; hours: number };
  available_charts: RcxChartOption[];
  disabled_charts: { chart_id: string; title: string; reason: string }[];
  sections: { id: string; label: string }[];
  warnings: string[];
  fault_summary: { active_faults: number; total_fault_hours: number };
  fault_rows: unknown[];
  report_bundles?: {
    bundles: RcxBundle[];
    default_bundle_ids?: string[];
    families?: Record<string, { label: string; count: number }>;
  };
  diagnostics?: { hints?: string[]; roles_resolved?: Record<string, string> };
};

function normalizePreview(raw: Record<string, unknown>): RcxPreviewResponse {
  const avail = (raw.available_charts as Record<string, unknown>[]) ?? [];
  const disabled = (raw.disabled_charts as Record<string, unknown>[]) ?? [];
  return {
    ...(raw as unknown as RcxPreviewResponse),
    available_charts: avail.map((c) => ({
      chart_id: String(c.chart_id ?? c.id ?? ""),
      title: String(c.title ?? c.label ?? c.chart_id ?? ""),
      equipment_id: c.equipment_id as string | undefined,
      equipment_type: c.equipment_type as string | undefined,
      partial_note: c.partial_note as string | undefined,
    })),
    disabled_charts: disabled.map((c) => ({
      chart_id: String(c.chart_id ?? c.id ?? ""),
      title: String(c.title ?? c.label ?? ""),
      reason: String(c.reason ?? ""),
    })),
    sections: ((raw.sections as Record<string, unknown>[]) ?? []).map((s) => ({
      id: String(s.id ?? ""),
      label: String(s.label ?? s.id ?? ""),
    })),
  };
}

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
  start?: string;
  end?: string;
  scope?: string;
  bundle_ids?: string[];
  equipment_ids?: string[];
  catalog_only?: boolean;
  include_previews?: boolean;
}): Promise<RcxPreviewResponse> {
  const raw = await apiFetch<Record<string, unknown>>("/api/reports/rcx/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return normalizePreview(raw);
}

export type RcxSavedReport = {
  filename: string;
  size_bytes: number;
  saved_at: string;
  download_path?: string;
  preview_path?: string;
};

export async function fetchRcxReportList(limit = 50): Promise<{ reports: RcxSavedReport[]; count: number }> {
  return apiFetch(`/api/reports/rcx/list?limit=${limit}`);
}

export function rcxReportDownloadUrl(filename: string): string {
  return `${getBridgeBase()}/api/reports/rcx/download/${encodeURIComponent(filename)}`;
}

export async function fetchRcxReportBlob(filename: string): Promise<Blob> {
  const res = await fetch(rcxReportDownloadUrl(filename), { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  return res.blob();
}

export async function deleteRcxReport(filename: string): Promise<void> {
  const res = await fetch(`${getBridgeBase()}/api/reports/rcx/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Delete failed (${res.status})`);
  }
}

export async function downloadRcxReport(body: {
  site_id?: string;
  hours?: number;
  start?: string;
  end?: string;
  scope?: string;
  bundle_ids?: string[];
  equipment_ids?: string[];
  sections?: string[];
  charts?: string[];
}): Promise<Blob> {
  const charts = (body.charts ?? []).filter((c): c is string => Boolean(c && String(c).trim()));
  const res = await fetch(`${getBridgeBase()}/api/reports/rcx/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ ...body, charts }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Report failed (${res.status})`);
  }
  return { blob: await res.blob(), savedFilename: res.headers.get("X-OpenFDD-Saved-Filename") };
}
