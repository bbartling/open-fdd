import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { MeteringPage } from "./MeteringPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
}));

vi.mock("../api/analyticsApi", async () => {
  const actual = await vi.importActual<typeof import("../api/analyticsApi")>(
    "../api/analyticsApi",
  );
  return {
    ...actual,
    postMetering: vi.fn(async () => ({
      schema_version: "analytics-envelope-v1",
      query_version: "metering-v1",
      generated_at: "2024-01-01T00:00:00Z",
      engine: "central-analytics-v1",
      warnings: ["metering: monthly kWh sum only"],
      rows: [
        { period: "2024-01", kwh: 150.5, n_rows: 2 },
        { period: "2024-02", kwh: 200, n_rows: 1 },
        { period: "2024-03", kwh: 175.25, n_rows: 1 },
      ],
      equipment: [],
      points: [],
      skipped: [],
      coverage: { total_kwh: 525.75, period_count: 3 },
    })),
    postRcxAhu: vi.fn(async () => ({
      schema_version: "analytics-envelope-v1",
      query_version: "rcx-ahu-v1",
      generated_at: "2024-01-01T00:00:00Z",
      engine: "central-analytics-v1",
      warnings: [],
      rows: [{ equipment_id: "AHU_1", has_sat_sp: true }],
      equipment: [],
      points: [],
      skipped: [],
    })),
  };
});

import { postMetering, postRcxAhu } from "../api/analyticsApi";

function renderPage(entry = "/metering?site=B1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <MeteringPage />
    </MemoryRouter>,
  );
}

describe("MeteringPage", () => {
  beforeEach(() => {
    vi.mocked(postMetering).mockClear();
    vi.mocked(postRcxAhu).mockClear();
  });

  it("runs metering and shows parity PASS", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-run"));
    fireEvent.click(screen.getByTestId("metering-run").querySelector("button")!);
    await waitFor(() => {
      expect(postMetering).toHaveBeenCalled();
      expect(screen.getByTestId("metering-parity").textContent).toContain("PASS");
      expect(screen.getByTestId("metering-table")).toBeTruthy();
    });
  });

  it("runs RCx AHU stub", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-rcx"));
    fireEvent.click(screen.getByTestId("metering-rcx").querySelector("button")!);
    await waitFor(() => {
      expect(postRcxAhu).toHaveBeenCalled();
      expect(screen.getByTestId("metering-rcx-result")).toBeTruthy();
    });
  });
});
