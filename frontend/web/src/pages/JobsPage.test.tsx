import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { JobsPage } from "./JobsPage";
import type { JobMeta } from "../api/jobsApi";

vi.mock("../api/jobsApi", () => ({
  listJobs: vi.fn(),
  getJob: vi.fn(),
  createJob: vi.fn(),
  patchJob: vi.fn(),
  archiveJob: vi.fn(),
  restoreJob: vi.fn(),
  duplicateJob: vi.fn(),
  isJobRevisionConflict: (err: unknown) =>
    err instanceof Error && err.name === "JobRevisionConflictError",
  JobRevisionConflictError: class JobRevisionConflictError extends Error {
    expectedRevision: string;
    currentRevision: string;
    constructor(expected: string, current: string) {
      super("conflict");
      this.name = "JobRevisionConflictError";
      this.expectedRevision = expected;
      this.currentRevision = current;
    }
  },
}));

import * as jobsApi from "../api/jobsApi";

const jobA: JobMeta = {
  schema_version: 1,
  job_id: "job-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  job_name: "Alpha",
  description: "first",
  status: "active",
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tags: [],
  meta_revision: "rev-1",
  revisions: {},
};

function clickWidgetButton(testId: string) {
  const wrap = screen.getByTestId(testId);
  const btn = wrap.querySelector("button");
  if (!btn) throw new Error(`no button in ${testId}`);
  fireEvent.click(btn);
}

function renderJobs(initial = "/jobs") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/jobs" element={<JobsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("JobsPage", () => {
  beforeEach(() => {
    vi.mocked(jobsApi.listJobs).mockReset();
    vi.mocked(jobsApi.getJob).mockReset();
    vi.mocked(jobsApi.createJob).mockReset();
    vi.mocked(jobsApi.patchJob).mockReset();
    vi.mocked(jobsApi.listJobs).mockResolvedValue([jobA]);
    vi.mocked(jobsApi.getJob).mockResolvedValue(jobA);
  });

  it("lists jobs and shows selected job meta_revision from URL", async () => {
    renderJobs("/jobs?job=job-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");

    await waitFor(() => {
      expect(screen.getByTestId("jobs-meta-revision").textContent).toContain("rev-1");
    });
    expect(jobsApi.listJobs).toHaveBeenCalledWith({ includeArchived: true });
    expect(jobsApi.getJob).toHaveBeenCalledWith("job-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
  });

  it("creates a job and selects it in the URL", async () => {
    const created = { ...jobA, job_id: "job-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", job_name: "Bravo" };
    vi.mocked(jobsApi.createJob).mockResolvedValue(created);
    vi.mocked(jobsApi.listJobs)
      .mockResolvedValueOnce([jobA])
      .mockResolvedValueOnce([jobA, created]);
    vi.mocked(jobsApi.getJob).mockResolvedValue(created);

    renderJobs();

    await waitFor(() => expect(screen.getByTestId("jobs-list-table")).toBeTruthy());

    fireEvent.change(screen.getByTestId("jobs-create-name"), { target: { value: "Bravo" } });
    clickWidgetButton("jobs-create");

    await waitFor(() => {
      expect(jobsApi.createJob).toHaveBeenCalledWith({ jobName: "Bravo", description: undefined });
    });
    expect(screen.getByTestId("jobs-notice").textContent).toContain("Bravo");
  });

  it("surfaces revision conflict on patch", async () => {
    renderJobs("/jobs?job=job-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");

    await waitFor(() => expect(screen.getByTestId("jobs-edit-name")).toBeTruthy());

    vi.mocked(jobsApi.patchJob).mockRejectedValue(
      new jobsApi.JobRevisionConflictError("rev-1", "rev-2"),
    );

    fireEvent.change(screen.getByTestId("jobs-edit-name"), { target: { value: "Alpha 2" } });
    clickWidgetButton("jobs-save");

    await waitFor(() => {
      expect(screen.getByTestId("jobs-revision-conflict").textContent).toContain("rev-2");
    });
  });

  it("toggles include archived query param", async () => {
    renderJobs();
    await waitFor(() => expect(jobsApi.listJobs).toHaveBeenCalled());

    const wrap = screen.getByTestId("jobs-include-archived");
    const input = wrap.querySelector('input[type="checkbox"]');
    if (!input) throw new Error("toggle input missing");
    fireEvent.click(input);

    await waitFor(() => {
      expect(jobsApi.listJobs).toHaveBeenCalledWith({ includeArchived: false });
    });
  });
});
