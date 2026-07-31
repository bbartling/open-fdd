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
      status: "active",
      archived: false,
      created_at: "",
      updated_at: "",
      tags: [],
      meta_revision: "rev-1",
      revisions: {},
    },
  ]),
}));

vi.mock("../api/reportsApi", () => ({
  createWattlabHandoff: vi.fn(async () => ({
    handoff_id: "handoff-9",
    job_id: "job-1",
    portable_zip_uri: "workspace://exports/demo.zip",
  })),
}));

import { createWattlabHandoff } from "../api/reportsApi";

describe("WattLabPage handoff", () => {
  beforeEach(() => {
    vi.mocked(createWattlabHandoff).mockClear();
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
});
