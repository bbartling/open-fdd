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

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => []),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/authApi", () => ({
  getAuthMe: vi.fn(async () => ({
    ok: true,
    username: "operator-1",
    role: "operator",
    auth_required: true,
  })),
  getStoredToken: vi.fn(() => null),
  logout: vi.fn(),
}));

import { getJob } from "../api/jobsApi";
import { uploadPackage } from "../api/uploadApi";
import { getAuthMe } from "../api/authApi";

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
    vi.mocked(getAuthMe).mockResolvedValue({
      ok: true,
      username: "operator-1",
      role: "operator",
      auth_required: true,
    });
  });

  it("renders file upload and import button for an operator", async () => {
    renderUpload();
    await waitFor(() => {
      expect(screen.getByTestId("upload-file").textContent).toMatch(
        /Building package zip/,
      );
    });
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
    expect(screen.getByTestId("upload-page").textContent).toMatch(
      /same ingest path and active-site handoff/,
    );
  });

  it("shows success after upload", async () => {
    vi.mocked(uploadPackage).mockResolvedValue({
      ok: true,
      building_id: "BUILDING_9",
      equipment_written: 2,
      total_rows: 500,
    });

    renderUpload();
    await waitFor(() => {
      expect(screen.getByTestId("upload-file")).toBeTruthy();
    });
    const uploadRoot = screen.getByTestId("upload-page");
    const input = uploadRoot.querySelector(
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
    expect(screen.getByTestId("upload-goto-overview").getAttribute("href")).toBe(
      "/?site=BUILDING_9",
    );
    const disclosure = screen.getByTestId("upload-result-disclosure");
    expect(disclosure.tagName).toBe("DETAILS");
    expect(disclosure.hasAttribute("open")).toBe(false);
    expect(screen.getByTestId("upload-result-json").textContent).toMatch(/BUILDING_9/);
    expect(disclosure.querySelector("pre")).toBe(screen.getByTestId("upload-result-json"));
    fireEvent.click(screen.getByText("Import response"));
    expect(disclosure.hasAttribute("open")).toBe(true);
    const link = screen.getByRole("link", { name: /continue to mapping/i });
    expect(link.getAttribute("href")).toBe("/mapping?site=BUILDING_9");
  });

  it("hides import controls for a viewer", async () => {
    vi.mocked(getAuthMe).mockResolvedValue({
      ok: true,
      username: "viewer-1",
      role: "viewer",
      auth_required: true,
    });
    renderUpload();
    await waitFor(() => {
      expect(getAuthMe).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("upload-submit")).toBeNull();
    expect(screen.queryByTestId("upload-file")).toBeNull();
    expect(screen.getByTestId("upload-page")).toBeTruthy();
  });
});
