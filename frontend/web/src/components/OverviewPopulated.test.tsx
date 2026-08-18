import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { OverviewPopulated } from "./OverviewPopulated";

const emptyOverview = {
  ok: true,
  building_id: "B1",
  source: "test",
  elapsed_s: 0.1,
  equipment_count: 2,
  equipment_ids: ["AHU_1", "BOILER_1"],
  has_weather: false,
  span: {
    start: "2026-03-16T00:40:00",
    end: "2026-07-17T10:00:00",
    span_hours: 2961.3,
  },
  motor_weekly: { caption: "both AHUs", plants: [], table: [] },
  mech_cooling: {
    caption: "",
    figure: null,
    bins: [],
    coverage: [],
    n_included: null,
    n_excluded: null,
  },
  economizer_weather: { caption: "", table: [] },
  economizer_free_cooling: {
    caption: "",
    metrics: [
      { equipment_id: "AHU_1" },
      { equipment_id: "AHU_2" },
    ],
    delta_scatter: { data: [{ x: [1], y: [1] }], layout: {}, meta: {} },
    mat_residual: { data: [{ x: [1], y: [1] }], layout: {}, meta: {} },
    temps_overlay: { data: [{ x: [1], y: [1] }], layout: {}, meta: {} },
    overlay_equipment_id: "AHU_1",
    skipped: [],
  },
  bas_vs_web_oat: { overlay: null, histogram: null, hist_table: [] },
  schedule: {},
  devices_by_type: [],
  error: null,
};

const { fetchCentralOverview } = vi.hoisted(() => ({
  fetchCentralOverview: vi.fn(async () => emptyOverview),
}));

vi.mock("../api/fddApi", () => ({
  getFddStatus: vi.fn(async () => ({
    ok: true,
    rule_count: 63,
    rules_dir: "sql_rules",
    rules_dir_exists: true,
  })),
  listFddRules: vi.fn(async () => [
    ...Array.from({ length: 59 }, (_, i) => ({ rule_id: `COOKBOOK-${i}` })),
    { rule_id: "FAN-RUNTIME-HOURS" },
    { rule_id: "AVG-ZONE-TEMP" },
    { rule_id: "ZONE-COMFORT-PCT" },
    { rule_id: "FAULT-ELAPSED-HOURS" },
  ]),
  getFddResults: vi.fn(async () => []),
  runFdd: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    equipment: [
      {
        equipment_id: "AHU_1",
        equipment_type: "AHU",
        sampling: {
          row_count: 35536,
          first_timestamp: "2026-03-16T00:40:00",
          last_timestamp: "2026-07-17T10:00:00",
        },
      },
      {
        equipment_id: "BOILER_1",
        equipment_type: "boiler",
        sampling: {
          row_count: 8,
          first_timestamp: "2026-03-16T00:40:00",
          last_timestamp: "2026-07-17T10:00:00",
        },
      },
      {
        equipment_id: "weather",
        equipment_type: "weather",
        sampling: {
          row_count: 999999,
          first_timestamp: "2020-01-01T00:00:00",
          last_timestamp: "2029-12-31T00:00:00",
        },
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: { params: {} } })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/centralOverview", () => ({
  fetchCentralOverview,
}));

vi.mock("../api/analyticsApi", () => ({
  postInspect: vi.fn(async () => ({
    coverage: {},
    points: [],
    warnings: [],
  })),
  postVavHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "vav-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        equipment_id: "VAV_1",
        score_label: "0/3",
        broken_box: false,
        poor_zone_performance: false,
        rogue_damper: false,
        confidence: "high",
        parent_ahu: "AHU_1",
      },
    ],
    equipment: [],
    points: [],
    skipped: [],
    coverage: { groups: { "3/3": 0, "2/3": 0, "1/3": 0, "0/3": 1, "?/3": 0 } },
  })),
  postAhuHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "ahu-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
    coverage: { groups: {} },
  })),
  postChillerHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "chiller-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
    coverage: { groups: {} },
  })),
  postBoilerHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "boiler-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
    coverage: { groups: {} },
  })),
  postHpHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "hp-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
    coverage: { groups: {} },
  })),
}));

vi.mock("../api/csvDownload", () => ({ downloadRowsCsv: vi.fn() }));

vi.mock("./widgets/PlotlyHost", () => ({
  PlotlyHost: ({ testId }: { testId?: string }) => (
    <div data-testid={testId ?? "plotly"} />
  ),
}));

const EQUIPMENT = [
  { equipment_id: "AHU_1", equipment_type: "AHU" },
  { equipment_id: "BOILER_1", equipment_type: "boiler" },
];

function renderOverview() {
  return render(
    <MemoryRouter>
      <OverviewPopulated
        buildingId="B1"
        equipmentId="AHU_1"
        equipment={EQUIPMENT}
        unitSystem="imperial"
        onEquipmentChange={vi.fn()}
      />
    </MemoryRouter>,
  );
}

describe("OverviewPopulated metric isolation", () => {
  beforeEach(() => {
    fetchCentralOverview.mockClear();
    fetchCentralOverview.mockResolvedValue(emptyOverview);
  });

  it("does not auto-run analytics; Update analytics loads charts and keeps mapping rows/span", async () => {
    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId("overview-idle-hint")).toBeTruthy();
    });
    expect(fetchCentralOverview).not.toHaveBeenCalled();
    expect(screen.getByTestId("overview-rule-count").textContent).toContain("59");
    expect(screen.getByTestId("overview-rule-caption").textContent).toMatch(
      /\+4 SQL rollups/,
    );

    fireEvent.click(
      screen.getByTestId("overview-refresh").querySelector("button")!,
    );

    await waitFor(() => {
      expect(fetchCentralOverview).toHaveBeenCalled();
      expect(screen.getByTestId("overview-row-count").textContent).toContain(
        "35536",
      );
    });
    expect(screen.getByTestId("overview-kind").textContent).toMatch(/ahu/i);
    expect(screen.getByTestId("overview-kind").textContent).not.toMatch(/AHU/);
    expect(screen.getByTestId("overview-start").textContent).toContain(
      "2026-03-16 00:40",
    );
    expect(screen.getByTestId("overview-end").textContent).toContain(
      "2026-07-17 10:00",
    );
    expect(screen.getByTestId("overview-span").textContent).toContain("2961.3");
  });

  it("has tables and health matrices, not Overview Plotly hosts", async () => {
    renderOverview();
    fireEvent.click(
      screen.getByTestId("overview-refresh").querySelector("button")!,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-charts-ready")).toBeTruthy();
    });
    expect(screen.queryByTestId("overview-inspect-eq")).toBeNull();
    expect(screen.queryByTestId("overview-data-inspection")).toBeNull();
    for (const id of [
      "overview-motor-air-plot",
      "overview-mech-plot",
      "overview-econ-delta-plot",
      "overview-econ-mat-resid-plot",
      "overview-econ-temps-plot",
      "overview-bas-overlay-plot",
      "overview-bas-hist-plot",
      "overview-inspect-plot",
    ]) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
    expect(screen.getByTestId("overview-ahu-health")).toBeTruthy();
    expect(screen.getByTestId("overview-chiller-health")).toBeTruthy();
    expect(screen.getByTestId("overview-boiler-health")).toBeTruthy();
    expect(screen.getByTestId("overview-hp-health")).toBeTruthy();
    expect(screen.getByTestId("overview-vav-health")).toBeTruthy();
  });

  it("does not render an Overview equipment picker", async () => {
    renderOverview();
    await waitFor(() => {
      expect(screen.getByTestId("overview-idle-hint")).toBeTruthy();
    });
    expect(screen.queryByTestId("overview-equipment-select")).toBeNull();
  });
});
