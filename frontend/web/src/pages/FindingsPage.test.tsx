import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { FindingsPage } from "./FindingsPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
}));

vi.mock("../api/fddApi", async () => {
  const actual = await vi.importActual<typeof import("../api/fddApi")>(
    "../api/fddApi",
  );
  return {
    ...actual,
    getFddResults: vi.fn(),
    downloadTextFile: vi.fn(),
  };
});

import { downloadTextFile, getFddResults } from "../api/fddApi";

function renderFindings(entry = "/findings?site=B1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <FindingsPage />
    </MemoryRouter>,
  );
}

describe("FindingsPage", () => {
  beforeEach(() => {
    vi.mocked(getFddResults).mockResolvedValue([
      {
        rule_id: "FC1",
        equipment_id: "AHU_1",
        status: "FAULT",
        fault_hours: 2,
        missing_roles: [],
      },
      {
        rule_id: "FC1",
        equipment_id: "VAV_1",
        status: "PASS",
        fault_hours: 0,
        missing_roles: [],
      },
    ]);
    vi.mocked(downloadTextFile).mockClear();
  });

  it("loads results for building and filters by status", async () => {
    renderFindings();
    await waitFor(() => {
      expect(screen.getByTestId("findings-count").textContent).toMatch(
        /Showing 2 of 2/,
      );
    });
    const statusSelect = screen
      .getByTestId("findings-status-select")
      .querySelector("select")!;
    fireEvent.change(statusSelect, { target: { value: "FAULT" } });
    await waitFor(() => {
      expect(screen.getByTestId("findings-count").textContent).toMatch(
        /Showing 1 of 2/,
      );
    });
  });

  it("downloads JSON artifact", async () => {
    renderFindings();
    await waitFor(() => screen.getByTestId("findings-download-json"));
    fireEvent.click(
      screen.getByTestId("findings-download-json").querySelector("button")!,
    );
    expect(downloadTextFile).toHaveBeenCalled();
    const [filename, content] = vi.mocked(downloadTextFile).mock.calls[0];
    expect(filename).toMatch(/fdd_results_B1\.json/);
    expect(String(content)).toMatch(/openfdd_fdd_results_v1/);
  });
});
