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
    postRcxPreset: vi.fn(async () => ({
      schema_version: "analytics-envelope-v1",
      query_version: "rcx-preset-meter_elec_cdd-v1",
      generated_at: "2024-01-01T00:00:00Z",
      engine: "central-analytics-v1",
      warnings: [],
      rows: [],
      equipment: [],
      points: [
        {
          equipment_id: "M_ELEC",
          month: "2024-01",
          energy: 100,
          degree_days: 12,
        },
        {
          equipment_id: "M_ELEC",
          month: "2024-02",
          energy: 120,
          degree_days: 18,
        },
      ],
      skipped: [],
      coverage: {
        title: "Electric × CDD",
        chart_kind: "metering",
        meter_kind: "electric",
      },
    })),
  };
});

vi.mock("../api/vibeCharts", async () => {
  const actual = await vi.importActual<typeof import("../api/vibeCharts")>(
    "../api/vibeCharts",
  );
  return {
    ...actual,
    meteringCharts: vi.fn(() => ({
      data: [{ type: "bar", name: "stub", x: ["2024-01"], y: [1] }],
      layout: {},
      meta: { point_count: 1, provenance: "test" },
    })),
  };
});

import { postMetering, postRcxPreset } from "../api/analyticsApi";

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
    vi.mocked(postRcxPreset).mockClear();
  });

  it("runs metering and shows parity PASS", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-run"));
    fireEvent.click(screen.getByTestId("metering-run").querySelector("button")!);
    await waitFor(() => {
      expect(postMetering).toHaveBeenCalled();
      expect(screen.getByTestId("metering-parity").textContent).toContain("PASS");
      expect(screen.getByTestId("metering-table")).toBeTruthy();
      expect(screen.getByTestId("metering-plot")).toBeTruthy();
    });
  });

  it("runs RCx metering preset", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-preset-run"));
    fireEvent.click(
      screen.getByTestId("metering-preset-run").querySelector("button")!,
    );
    await waitFor(() => {
      expect(postRcxPreset).toHaveBeenCalled();
      expect(screen.getByTestId("metering-plot")).toBeTruthy();
    });
  });
});
