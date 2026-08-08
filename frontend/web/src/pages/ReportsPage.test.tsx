import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReportsPage } from "./ReportsPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    building_id: "B1",
    equipment: [
      {
        equipment_id: "VAV_1",
        equipment_type: "VAV",
        ok: true,
        roles: { zone_t: "zone_t" },
        columns: [{ column: "zone_air_temp", role: "zone_t", status: "mapped" }],
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: {} })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => [
    {
      rule_id: "VAV-1",
      description: "Comfort",
      required_roles: ["zone_t"],
      parameter_count: 0,
    },
  ]),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
  getFddResults: vi.fn(async () => [
    { rule_id: "VAV-1", equipment_id: "VAV_1", status: "FAULT" },
  ]),
  getFddSeries: vi.fn(async () => ({
    ok: true,
    equipment_id: "VAV_1",
    rule_id: "VAV-1",
    roles: ["zone_t"],
    rows: [
      { timestamp_utc: "2024-01-01T00:00:00Z", zone_t: 70, confirmed_fault: 0 },
      { timestamp_utc: "2024-01-01T00:05:00Z", zone_t: 71, confirmed_fault: 1 },
    ],
    downsampled: false,
    max_points: 5000,
  })),
}));

vi.mock("../api/analyticsApi", () => ({
  listFddEquipment: vi.fn(async () => [
    { equipment_id: "VAV_1", equipment_type: "VAV" },
  ]),
  postSensorHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "sensor-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        equipment_id: "VAV_1",
        role: "zone_t",
        coverage_pct: 100,
        missingness: 0,
        flatline_flag: false,
        n: 10,
        n_finite: 10,
      },
    ],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postInspect: vi.fn(async () => ({
    points: [],
    warnings: [],
  })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

import { getFddSeries } from "../api/fddApi";

function renderPlots(entry = "/reports?site=B1&eq=VAV_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ReportsPage />
    </MemoryRouter>,
  );
}

describe("ReportsPage FDD Plots", () => {
  beforeEach(() => {
    vi.mocked(getFddSeries).mockClear();
  });

  it("shows FDD Plots title without artifacts mode", async () => {
    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-page")).toBeTruthy();
    });
    expect(screen.getByRole("heading", { level: 1, name: "FDD Plots" })).toBeTruthy();
    expect(screen.queryByTestId("reports-mode")).toBeNull();
    expect(screen.queryByTestId("reports-artifacts")).toBeNull();
  });

  it("loads series and renders chart + preview", async () => {
    renderPlots();
    await waitFor(() => {
      const btn = screen.getByTestId("plots-load").querySelector("button");
      expect(btn?.disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId("plots-load").querySelector("button")!);
    await waitFor(() => {
      expect(getFddSeries).toHaveBeenCalledWith("VAV_1", "VAV-1");
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
      expect(screen.getByTestId("plots-preview-table")).toBeTruthy();
    });
  });
});
