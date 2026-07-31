import { apiFetch } from "./client";

export interface EngFinding {
  finding_id: string;
  correlation_key: string;
  run_id?: string;
  evidence?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FindingsDocument {
  schema_version: string;
  findings: EngFinding[];
}

export interface Disposition {
  correlation_key: string;
  status: string;
  notes?: string;
  updated_at?: string;
  updated_by?: string;
  [key: string]: unknown;
}

export interface DispositionsDocument {
  schema_version: string;
  dispositions: Disposition[];
}

export interface FindingsGetResponse {
  ok: boolean;
  findings: FindingsDocument;
}

export interface DispositionsGetResponse {
  ok: boolean;
  dispositions: DispositionsDocument;
}

export async function getJobFindings(jobId: string): Promise<FindingsDocument> {
  const body = await apiFetch<FindingsGetResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/findings`,
  );
  return body.findings ?? { schema_version: "1", findings: [] };
}

export async function putJobFindings(
  jobId: string,
  findings: FindingsDocument,
  findingsRevision?: string,
): Promise<void> {
  await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/findings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      findings,
      findings_revision: findingsRevision,
    }),
  });
}

export async function getJobDispositions(
  jobId: string,
): Promise<DispositionsDocument> {
  const body = await apiFetch<DispositionsGetResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/dispositions`,
  );
  return body.dispositions ?? { schema_version: "1", dispositions: [] };
}

export async function putJobDispositions(
  jobId: string,
  dispositions: DispositionsDocument,
): Promise<void> {
  await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/dispositions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(dispositions),
  });
}

export function upsertDisposition(
  doc: DispositionsDocument,
  next: Disposition,
): DispositionsDocument {
  const others = doc.dispositions.filter(
    (d) => d.correlation_key !== next.correlation_key,
  );
  return {
    schema_version: doc.schema_version || "1",
    dispositions: [...others, next],
  };
}
