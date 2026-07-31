import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { UploadPage } from "./UploadPage";

vi.mock("../api/jobsApi", () => ({
  getJob: vi.fn(),
}));

vi.mock("../api/uploadApi", () => ({
  uploadPackage: vi.fn(),
  packageDatasetId: (r: { building_id?: string }) => r.building_id,
}));

import { getJob } from "../api/jobsApi";
import { uploadPackage } from "../api/uploadApi";

function renderUpload(initialEntries = "/upload") {
  return render(
    <MemoryRouter initialEntries={[initialEntries]}>
      <UploadPage />
    </MemoryRouter>,
  );
}

describe("UploadPage", () => {
  beforeEach(() => {
    vi.mocked(getJob).mockReset();
    vi.mocked(uploadPackage).mockReset();
  });

  it("renders file upload and import button", () => {
    renderUpload();
    expect(screen.getByText("Building package zip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /import package/i })).toBeDisabled();
  });

  it("shows session job context when ?job= is set", async () => {
    vi.mocked(getJob).mockResolvedValue({
      schema_version: 1,
      job_id: "job-1",
      job_name: "Alpha",
      status: "active",
      archived: false,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      tags: [],
      meta_revision: "r1",
      revisions: {},
    });
    renderUpload("/upload?job=job-1");
    await waitFor(() => {
      expect(screen.getByText(/Alpha/)).toBeInTheDocument();
    });
    expect(screen.getByText(/does not yet associate uploads with jobs/i)).toBeInTheDocument();
  });

  it("shows success after upload", async () => {
    vi.mocked(uploadPackage).mockResolvedValue({
      ok: true,
      building_id: "BUILDING_9",
      equipment_written: 2,
      total_rows: 500,
    });

    renderUpload();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["zip"], "demo.zip", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /import package/i }));

    await waitFor(() => {
      expect(screen.getByText(/BUILDING_9/)).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /continue to mapping/i })).toHaveAttribute(
      "href",
      "/mapping?site=BUILDING_9",
    );
  });
});
