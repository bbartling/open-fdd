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

vi.mock("../api/exportApi", () => ({
  createExport: vi.fn(async () => ({
    export_id: "export-1",
    job_id: "job-1",
    building_id: "BUILDING_100",
    profile: "summary",
    filename: "openfdd_engineering_BUILDING_100_summary.zip",
    download_url: "/api/jobs/job-1/exports/export-1/download",
  })),
  downloadExport: vi.fn(async () => undefined),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

import { createWattlabHandoff } from "../api/reportsApi";
import { createExport, downloadExport } from "../api/exportApi";

describe("WattLabPage handoff", () => {
  beforeEach(() => {
    vi.mocked(createWattlabHandoff).mockClear();
    vi.mocked(createExport).mockClear();
    vi.mocked(downloadExport).mockClear();
  });

  it("renders one Dump page without Export multi-page radio", async () => {
    render(
      <MemoryRouter initialEntries={["/wattlab?job=job-1"]}>
        <WattLabPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByTestId("wattlab-page"));
    expect(screen.getByRole("heading", { name: "Dump" })).toBeTruthy();
    expect(screen.queryByTestId("wattlab-page-radio")).toBeNull();
    expect(screen.getByTestId("dump-related-links").textContent).toMatch(
      /Upload/,
    );
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
        expect.objectContaining({
          portable_zip_uri: expect.any(String),
          wattlab_studio_page: "Dump",
        }),
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
      expect(createExport).toHaveBeenCalledWith(
        "job-1",
        "BUILDING_100",
        "summary",
      );
      expect(screen.getByTestId("wattlab-dump-meta")).toBeTruthy();
    });
  });
});
