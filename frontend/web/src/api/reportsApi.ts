import { apiFetch } from "./client";

/** Stable paths for nightly gate 11 (#549) — keep in main bundle via App import. */
export const REPORTS_ROUTE = "/reports";
export const REPORTS_API_ROOT = "/api/reports";

export interface ReportRecord {
  report_id?: string;
  report_type?: string;
  template_id?: string;
  kind?: string;
  title?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface ReportsListResponse {
  ok?: boolean;
  records?: ReportRecord[];
  [key: string]: unknown;
}

export async function listReports(): Promise<ReportRecord[]> {
  const body = await apiFetch<ReportsListResponse>("/api/reports");
  return Array.isArray(body.records) ? body.records : [];
}

export async function listReportTemplates(): Promise<unknown> {
  return apiFetch("/api/reports/templates");
}

export async function createReportDraft(
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return apiFetch("/api/reports/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getEngineeringFindingsReport(): Promise<Record<string, unknown>> {
  return apiFetch("/api/reports/engineering-findings");
}

export async function createWattlabHandoff(
  jobId: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const body = await apiFetch<{ ok: boolean; handoff: Record<string, unknown> }>(
    `/api/jobs/${encodeURIComponent(jobId)}/wattlab/handoffs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return body.handoff ?? body;
}
