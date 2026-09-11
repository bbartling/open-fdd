import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExportPage } from "./WattLabPage";

vi.mock("../api/jobsApi", () => ({
  listJobs: vi.fn(async () => []),
  createJob: vi.fn(async () => ({
    job_id: "job-new",
    job_name: "E+ dump",
  })),
}));

vi.mock("../api/exportApi", () => ({
  createExport: vi.fn(async () => ({
    export_id: "export-1",
    job_id: "job-1",
    building_id: "BUILDING_100",
    profile: "summary",
    filename: "BUILDING_100_summary.zip",
    download_url: "/api/jobs/job-1/exports/export-1/download",
  })),
  downloadExport: vi.fn(async () => undefined),
}));

vi.mock("../session", () => ({
  useSessionQuery: () => ({
    query: { jobId: "job-1", siteId: "BUILDING_100" },
    setQuery: vi.fn(),
  }),
}));

describe("ExportPage / Dump", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a single Dump button with no Related links or profile radios", async () => {
    render(
      <MemoryRouter initialEntries={["/export?job=job-1&site=BUILDING_100"]}>
        <ExportPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByTestId("wattlab-page"));
    expect(screen.queryByTestId("dump-related-links")).toBeNull();
    expect(screen.queryByTestId("wattlab-profile")).toBeNull();
    expect(screen.queryByTestId("wattlab-handoff")).toBeNull();
    expect(screen.getByTestId("wattlab-build-dump")).toBeTruthy();
  });

  it("builds and downloads one summary dump", async () => {
    const { createExport, downloadExport } = await import("../api/exportApi");
    render(
      <MemoryRouter
        initialEntries={["/export?job=job-1&site=BUILDING_100"]}
      >
        <ExportPage />
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
      expect(downloadExport).toHaveBeenCalled();
    });
  });
});
