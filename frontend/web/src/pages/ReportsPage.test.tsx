import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    { equipment_id: "AHU_10", equipment_type: "AHU" },
    { equipment_id: "AHU_1", equipment_type: "AHU" },
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
import { preferredPlotRuleId, matchesStatusFilter } from "./ReportsPage";

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
      expect(getFddSeries).toHaveBeenCalledWith("VAV_1", "VAV-1", "B1");
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
      expect(screen.getByTestId("plots-preview-table")).toBeTruthy();
      expect(screen.queryByTestId("plots-no-fault")).toBeNull();
    });
  });

  it("lists full inventory including equipment without results", async () => {
    renderPlots("/reports?site=B1");
    await waitFor(() => {
      const select = screen
        .getByTestId("plots-equipment-select")
        .querySelector("select");
      const values = [...(select?.options ?? [])].map((o) => o.value);
      expect(values).toEqual(["AHU_1", "AHU_10", "VAV_1"]);
      expect(values).not.toContain("");
    });
  });

  it("shows status filter radios and result cards", async () => {
    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-status-filter")).toBeTruthy();
      expect(screen.getByTestId("plots-card-VAV-1")).toBeTruthy();
    });
  });

  it("soft-shows series chart when confirmed_fault overlay is absent", async () => {
    vi.mocked(getFddSeries).mockResolvedValueOnce({
      ok: true,
      equipment_id: "VAV_1",
      rule_id: "VAV-1",
      roles: ["zone_t"],
      rows: [
        { timestamp_utc: "2024-01-01T00:00:00Z", zone_t: 70 },
        { timestamp_utc: "2024-01-01T00:05:00Z", zone_t: 71 },
      ],
      downsampled: false,
      max_points: 5000,
      has_confirmed_fault: false,
    });
    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
      expect(screen.getByTestId("plots-no-fault").textContent).toMatch(
        /No fault lane yet/,
      );
    });
  });
});

describe("preferredPlotRuleId", () => {
  const rules = [
    { rule_id: "VAV-1", description: "a" },
    { rule_id: "VAV-2", description: "b" },
  ];

  it("prefers FAULT then first applicable", () => {
    expect(
      preferredPlotRuleId(
        rules,
        [{ rule_id: "VAV-2", equipment_id: "VAV_1", status: "FAULT" }],
        "VAV_1",
      ),
    ).toBe("VAV-2");
    expect(preferredPlotRuleId(rules, [], "VAV_1")).toBe("VAV-1");
  });

  it("matches SKIPPED* under SKIPPED filter", () => {
    expect(matchesStatusFilter("SKIPPED_MISSING_ROLES", "SKIPPED")).toBe(true);
    expect(matchesStatusFilter("PASS", "FAULT")).toBe(false);
    expect(matchesStatusFilter("FAULT", "All")).toBe(true);
  });
});
