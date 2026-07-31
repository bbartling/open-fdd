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

function renderUpload(initialEntry = "/upload") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
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
    expect(screen.getByText("Building package zip")).toBeTruthy();
    const btn = screen.getByTestId("upload-submit").querySelector("button");
    expect(btn?.disabled).toBe(true);
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
      expect(screen.getByTestId("upload-job-context").textContent).toMatch(/Alpha/);
    });
    expect(document.body.textContent).toMatch(/does not yet associate/);
  });

  it("shows success after upload", async () => {
    vi.mocked(uploadPackage).mockResolvedValue({
      ok: true,
      building_id: "BUILDING_9",
      equipment_written: 2,
      total_rows: 500,
    });

    renderUpload();
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["zip"], "demo.zip", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(
      screen.getByTestId("upload-submit").querySelector("button")!,
    );

    await waitFor(() => {
      expect(screen.getByTestId("upload-success").textContent).toMatch(
        /BUILDING_9/,
      );
    });
    const link = screen.getByRole("link", { name: /continue to mapping/i });
    expect(link.getAttribute("href")).toBe("/mapping?site=BUILDING_9");
  });
});
