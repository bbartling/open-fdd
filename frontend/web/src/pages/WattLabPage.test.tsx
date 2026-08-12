import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { WattLabPage } from "./WattLabPage";

vi.mock("../api/jobsApi", () => ({
  listJobs: vi.fn(async () => [
    {
      schema_version: 1,
      job_id: "job-1",
      job_name: "Alpha",
      site_id: "BUILDING_100",
      status: "active",
      archived: false,
      created_at: "",
      updated_at: "",
      tags: [],
      meta_revision: "rev-1",
      revisions: {},
    },
  ]),
  createJob: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["BUILDING_100"]),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/reportsApi", () => ({
  createWattlabHandoff: vi.fn(async () => ({
    handoff_id: "handoff-9",
    job_id: "job-1",
    portable_zip_uri: "workspace://exports/demo.zip",
  })),
}));

vi.mock("../api/wattlabApi", () => ({
  createDump: vi.fn(async () => ({
    dump_id: "dump-1",
    job_id: "job-1",
    building_id: "BUILDING_100",
    profile: "summary",
    filename: "wattlab_dump_BUILDING_100.zip",
    download_url: "/api/jobs/job-1/wattlab/dumps/dump-1/download",
  })),
  downloadDump: vi.fn(async () => undefined),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

import { createWattlabHandoff } from "../api/reportsApi";
import { createDump, downloadDump } from "../api/wattlabApi";

describe("WattLabPage handoff", () => {
  beforeEach(() => {
    vi.mocked(createWattlabHandoff).mockClear();
    vi.mocked(createDump).mockClear();
    vi.mocked(downloadDump).mockClear();
  });

  it("creates a handoff for ?job=", async () => {
    render(
      <MemoryRouter initialEntries={["/wattlab?job=job-1"]}>
        <WattLabPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByTestId("wattlab-handoff"));
    fireEvent.click(
      screen.getByTestId("wattlab-handoff").querySelector("button")!,
    );
    await waitFor(() => {
      expect(createWattlabHandoff).toHaveBeenCalledWith(
        "job-1",
        expect.objectContaining({ portable_zip_uri: expect.any(String) }),
      );
      expect(screen.getByTestId("wattlab-notice").textContent).toMatch(
        /handoff-9/,
      );
    });
  });

  it("builds a dump for the selected site", async () => {
    render(
      <MemoryRouter
        initialEntries={["/wattlab?job=job-1&site=BUILDING_100"]}
      >
        <WattLabPage />
      </MemoryRouter>,
    );

    await waitFor(() => screen.getByTestId("wattlab-build-dump"));
    fireEvent.click(
      screen.getByTestId("wattlab-build-dump").querySelector("button")!,
    );

    await waitFor(() => {
      expect(createDump).toHaveBeenCalledWith(
        "job-1",
        "BUILDING_100",
        "summary",
      );
      expect(screen.getByTestId("wattlab-dump-meta")).toBeTruthy();
    });
  });
});
