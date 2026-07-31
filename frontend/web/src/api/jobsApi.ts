import { ApiClientError, apiFetch } from "./client";

export interface JobRevisions {
  dataset?: string | null;
  mapping?: string | null;
  config?: string | null;
  engine?: string | null;
}

export interface JobMeta {
  schema_version: number;
  job_id: string;
  job_name: string;
  description?: string | null;
  status: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  created_by?: string | null;
  site_id?: string | null;
  site_name?: string | null;
  building_name?: string | null;
  tags: string[];
  meta_revision: string;
  latest_run_id?: string | null;
  latest_findings_revision?: string | null;
  mapping_path?: string | null;
  revisions: JobRevisions;
}

export interface JobsListResponse {
  ok: boolean;
  jobs: JobMeta[];
}

export interface JobResponse {
  ok: boolean;
  job: JobMeta;
}

export interface JobRevisionConflictBody {
  ok: false;
  error: "revision_conflict";
  expected_revision: string;
  current_revision: string;
}

export class JobRevisionConflictError extends Error {
  readonly expectedRevision: string;
  readonly currentRevision: string;
  readonly status = 409;

  constructor(expected: string, current: string) {
    super(`Job revision conflict: expected ${expected}, current ${current}`);
    this.name = "JobRevisionConflictError";
    this.expectedRevision = expected;
    this.currentRevision = current;
  }
}

/** Parse legacy jobs CONFLICT JSON (not the standard error envelope). */
export function parseRevisionConflict(text: string): JobRevisionConflictBody | null {
  try {
    const body = JSON.parse(text) as unknown;
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      body.error === "revision_conflict" &&
      "expected_revision" in body &&
      "current_revision" in body &&
      typeof body.expected_revision === "string" &&
      typeof body.current_revision === "string"
    ) {
      return body as JobRevisionConflictBody;
    }
  } catch {
    // not JSON
  }
  return null;
}

export function isJobRevisionConflict(err: unknown): err is JobRevisionConflictError {
  return err instanceof JobRevisionConflictError;
}

export interface ListJobsParams {
  includeArchived?: boolean;
  status?: string;
  siteId?: string;
  tag?: string;
}

export function buildJobsListPath(params: ListJobsParams = {}): string {
  const q = new URLSearchParams();
  if (params.includeArchived !== undefined) {
    q.set("include_archived", String(params.includeArchived));
  }
  if (params.status) q.set("status", params.status);
  if (params.siteId) q.set("site_id", params.siteId);
  if (params.tag) q.set("tag", params.tag);
  const qs = q.toString();
  return qs ? `/api/jobs?${qs}` : "/api/jobs";
}

export interface CreateJobInput {
  jobName: string;
  description?: string;
}

export function buildCreateJobBody(input: CreateJobInput): {
  job_name: string;
  description?: string;
} {
  const body: { job_name: string; description?: string } = {
    job_name: input.jobName,
  };
  if (input.description !== undefined && input.description !== "") {
    body.description = input.description;
  }
  return body;
}

export interface PatchJobInput {
  jobName?: string;
  description?: string;
  expectedMetaRevision: string;
}

export function buildPatchJobBody(input: PatchJobInput): {
  job_name?: string;
  description?: string;
  expected_meta_revision: string;
} {
  return {
    ...(input.jobName !== undefined ? { job_name: input.jobName } : {}),
    ...(input.description !== undefined ? { description: input.description } : {}),
    expected_meta_revision: input.expectedMetaRevision,
  };
}

function rethrowIfRevisionConflict(err: unknown): never {
  if (err instanceof ApiClientError && err.status === 409) {
    const conflict = parseRevisionConflict(err.message);
    if (conflict) {
      throw new JobRevisionConflictError(
        conflict.expected_revision,
        conflict.current_revision,
      );
    }
  }
  throw err;
}

export async function listJobs(params: ListJobsParams = {}): Promise<JobMeta[]> {
  const body = await apiFetch<JobsListResponse>(buildJobsListPath(params));
  return body.jobs ?? [];
}

export async function getJob(jobId: string): Promise<JobMeta> {
  const body = await apiFetch<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}`);
  return body.job;
}

export async function createJob(input: CreateJobInput): Promise<JobMeta> {
  const body = await apiFetch<JobResponse>("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildCreateJobBody(input)),
  });
  return body.job;
}

export async function patchJob(jobId: string, input: PatchJobInput): Promise<JobMeta> {
  try {
    const body = await apiFetch<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPatchJobBody(input)),
    });
    return body.job;
  } catch (err) {
    rethrowIfRevisionConflict(err);
  }
}

export async function archiveJob(jobId: string): Promise<JobMeta> {
  const body = await apiFetch<JobResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/archive`,
    { method: "POST" },
  );
  return body.job;
}

export async function restoreJob(jobId: string): Promise<JobMeta> {
  const body = await apiFetch<JobResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/restore`,
    { method: "POST" },
  );
  return body.job;
}

export async function duplicateJob(jobId: string, newName?: string): Promise<JobMeta> {
  const body = await apiFetch<JobResponse>(
    `/api/jobs/${encodeURIComponent(jobId)}/duplicate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newName ? { new_name: newName } : {}),
    },
  );
  return body.job;
}
