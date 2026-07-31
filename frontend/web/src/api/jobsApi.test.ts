import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  buildCreateJobBody,
  buildJobsListPath,
  buildPatchJobBody,
  parseRevisionConflict,
  JobRevisionConflictError,
} from "./jobsApi";
import { ApiClientError } from "./client";

describe("jobsApi helpers", () => {
  it("buildJobsListPath encodes include_archived", () => {
    expect(buildJobsListPath()).toBe("/api/jobs");
    expect(buildJobsListPath({ includeArchived: false })).toBe(
      "/api/jobs?include_archived=false",
    );
    expect(buildJobsListPath({ includeArchived: true, status: "active" })).toBe(
      "/api/jobs?include_archived=true&status=active",
    );
  });

  it("buildCreateJobBody omits empty description", () => {
    expect(buildCreateJobBody({ jobName: "Alpha" })).toEqual({ job_name: "Alpha" });
    expect(buildCreateJobBody({ jobName: "Beta", description: "notes" })).toEqual({
      job_name: "Beta",
      description: "notes",
    });
  });

  it("buildPatchJobBody includes expected_meta_revision", () => {
    expect(
      buildPatchJobBody({
        jobName: "Renamed",
        description: "d",
        expectedMetaRevision: "rev-1",
      }),
    ).toEqual({
      job_name: "Renamed",
      description: "d",
      expected_meta_revision: "rev-1",
    });
  });

  it("parseRevisionConflict reads CONFLICT JSON", () => {
    const body = JSON.stringify({
      ok: false,
      error: "revision_conflict",
      expected_revision: "aaa",
      current_revision: "bbb",
    });
    expect(parseRevisionConflict(body)).toEqual({
      ok: false,
      error: "revision_conflict",
      expected_revision: "aaa",
      current_revision: "bbb",
    });
    expect(parseRevisionConflict(JSON.stringify({ ok: false, error: "other" }))).toBeNull();
  });

  it("JobRevisionConflictError carries revisions", () => {
    const err = new JobRevisionConflictError("exp", "cur");
    expect(err.expectedRevision).toBe("exp");
    expect(err.currentRevision).toBe("cur");
    expect(err.status).toBe(409);
  });
});

describe("jobsApi patch conflict mapping", () => {
  it("maps ApiClientError 409 body to revision conflict type", () => {
    const raw = JSON.stringify({
      ok: false,
      error: "revision_conflict",
      expected_revision: "old",
      current_revision: "new",
    });
    const apiErr = new ApiClientError(raw, {
      code: "http.error",
      retryable: false,
      requestId: "r1",
      status: 409,
    });
    const parsed = parseRevisionConflict(apiErr.message);
    expect(parsed?.current_revision).toBe("new");
  });
});

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

import { apiFetch } from "./client";
import {
  archiveJob,
  createJob,
  duplicateJob,
  getJob,
  listJobs,
  patchJob,
  restoreJob,
} from "./jobsApi";

const sampleJob = {
  schema_version: 1,
  job_id: "job-11111111-1111-1111-1111-111111111111",
  job_name: "Demo",
  description: "desc",
  status: "active",
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tags: [],
  meta_revision: "rev-a",
  revisions: {},
};

describe("jobsApi client calls", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("listJobs calls GET /api/jobs with query", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, jobs: [sampleJob] });
    const jobs = await listJobs({ includeArchived: false });
    expect(apiFetch).toHaveBeenCalledWith("/api/jobs?include_archived=false");
    expect(jobs).toHaveLength(1);
  });

  it("getJob fetches by id", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, job: sampleJob });
    const job = await getJob(sampleJob.job_id);
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/jobs/${encodeURIComponent(sampleJob.job_id)}`,
    );
    expect(job.job_name).toBe("Demo");
  });

  it("createJob POSTs job_name body", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, job: sampleJob });
    await createJob({ jobName: "Demo", description: "desc" });
    expect(apiFetch).toHaveBeenCalledWith("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_name: "Demo", description: "desc" }),
    });
  });

  it("patchJob POSTs expected_meta_revision and maps conflict", async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      new ApiClientError(
        JSON.stringify({
          ok: false,
          error: "revision_conflict",
          expected_revision: "rev-a",
          current_revision: "rev-b",
        }),
        {
          code: "http.error",
          retryable: false,
          requestId: "r",
          status: 409,
        },
      ),
    );
    await expect(
      patchJob(sampleJob.job_id, {
        jobName: "New",
        expectedMetaRevision: "rev-a",
      }),
    ).rejects.toMatchObject({
      name: "JobRevisionConflictError",
      currentRevision: "rev-b",
    });
  });

  it("archiveJob POSTs archive route", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, job: { ...sampleJob, archived: true } });
    await archiveJob(sampleJob.job_id);
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/jobs/${encodeURIComponent(sampleJob.job_id)}/archive`,
      { method: "POST" },
    );
  });

  it("restoreJob POSTs restore route", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, job: sampleJob });
    await restoreJob(sampleJob.job_id);
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/jobs/${encodeURIComponent(sampleJob.job_id)}/restore`,
      { method: "POST" },
    );
  });

  it("duplicateJob POSTs optional new_name", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, job: sampleJob });
    await duplicateJob(sampleJob.job_id, "Copy");
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/jobs/${encodeURIComponent(sampleJob.job_id)}/duplicate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: "Copy" }),
      },
    );
  });
});
