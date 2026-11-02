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
  deleteJob: vi.fn(),
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

vi.mock("../api/historianApi", () => ({
  getHistorianPoints: vi.fn(),
  purgeHistorian: vi.fn(),
}));

vi.mock("../api/authApi", async () => {
  const actual = await vi.importActual<typeof import("../api/authApi")>("../api/authApi");
  return { ...actual, getAuthMe: vi.fn() };
});

import * as jobsApi from "../api/jobsApi";
import { getAuthMe } from "../api/authApi";
import { getHistorianPoints, purgeHistorian } from "../api/historianApi";

const historianPoints = [
  {
    openfdd_key: "VAV_1.zone_temp",
    equipment_id: "VAV_1",
    equip_type: "vav",
    role: "zone-air-temp",
    unit: "degF",
    portal_point_id: "p-1",
    referenced: false,
  },
  {
    openfdd_key: "VAV_10.zone_temp",
    equipment_id: "VAV_10",
    equip_type: "vav",
    role: "zone-air-temp",
    unit: "degF",
    portal_point_id: "p-10",
    referenced: true,
  },
];

function mockRole(role: "viewer" | "operator" | "admin") {
  vi.mocked(getAuthMe).mockResolvedValue({
    ok: true,
    username: role,
    role,
    auth_required: true,
  } as Awaited<ReturnType<typeof getAuthMe>>);
}

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
    vi.mocked(getHistorianPoints).mockReset();
    vi.mocked(purgeHistorian).mockReset();
    vi.mocked(getHistorianPoints).mockResolvedValue({
      ok: true,
      building_id: "SITE_A",
      historian: "timescale",
      points: historianPoints,
    });
    mockRole("viewer");
  });

  it("shows a read-only device tree without purge controls for a viewer", async () => {
    renderJobs("/jobs?site=SITE_A");

    await waitFor(() => expect(screen.getByTestId("jobs-tree-equipment-VAV_1")).toBeTruthy());
    expect(getHistorianPoints).toHaveBeenCalledWith("SITE_A", expect.anything());
    expect(screen.getByTestId("jobs-tree-point-VAV_1.zone_temp").textContent).toContain(
      "orphaned",
    );
    expect(screen.queryByTestId("jobs-purge-equipment-VAV_1")).toBeNull();
    expect(screen.queryByTestId("jobs-purge-point-VAV_1.zone_temp")).toBeNull();
    expect(screen.queryByRole("textbox", { name: /role/i })).toBeNull();
  });

  it("purges one equipment after the operator confirms", async () => {
    mockRole("operator");
    vi.mocked(purgeHistorian).mockResolvedValue({
      ok: true,
      building_id: "SITE_A",
      equipment_id: "VAV_1",
      purge: {
        keys: ["VAV_1.zone_temp"],
        samples_deleted: 12,
        point_map_deleted: 1,
        role_map_deleted: 0,
      },
    });
    renderJobs("/jobs?site=SITE_A");

    await waitFor(() => expect(screen.getByTestId("jobs-purge-equipment-VAV_1")).toBeTruthy());
    clickWidgetButton("jobs-purge-equipment-VAV_1");
    expect(purgeHistorian).not.toHaveBeenCalled();
    expect(screen.getByTestId("jobs-purge-modal").textContent).toContain("equipment VAV_1");

    fireEvent.click(screen.getByTestId("jobs-purge-modal-confirm"));

    await waitFor(() => {
      expect(purgeHistorian).toHaveBeenCalledWith("SITE_A", {
        kind: "equipment",
        equipmentId: "VAV_1",
      });
    });
    expect(purgeHistorian).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.getByTestId("jobs-purge-notice").textContent).toContain("12 samples");
    });
    expect(getHistorianPoints).toHaveBeenCalledTimes(2);
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
    await waitFor(() => {
      expect(screen.getByTestId("jobs-notice").textContent).toContain("Bravo");
    });
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
