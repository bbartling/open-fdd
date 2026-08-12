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
  bas_vs_web_oat: { overlay: null, histogram: null },
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
  postInspect: vi.fn(async ({ equipment_ids }: { equipment_ids: string[] }) => ({
    coverage: {
      plottable_columns: ["sat", "mat", "rat"],
      columns_plotted: ["sat", "mat", "rat"],
      row_count: 1741158,
      first_timestamp: "2026-03-16T00:40:00",
      last_timestamp: "2026-03-22T23:15:00",
    },
    points: [
      {
        timestamp_utc: "2026-03-16T00:40:00",
        equipment_id: equipment_ids[0],
        sat: 55,
        mat: 60,
        rat: 70,
      },
    ],
    warnings: [],
  })),
}));

vi.mock("../api/csvDownload", () => ({ downloadRowsCsv: vi.fn() }));

vi.mock("./widgets/PlotlyHost", () => ({
  PlotlyHost: ({ testId }: { testId?: string }) => (
    <div data-testid={testId ?? "plotly"} />
  ),
}));

import { postInspect } from "../api/analyticsApi";

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
    vi.mocked(postInspect).mockClear();
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

  it("does not offer a column toggle and plots inspect without clearing overview", async () => {
    renderOverview();
    fireEvent.click(
      screen.getByTestId("overview-refresh").querySelector("button")!,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-charts-ready")).toBeTruthy();
    });
    expect(screen.queryByTestId("overview-inspect-cols-select")).toBeNull();
    expect(screen.queryByText(/Columns to plot/i)).toBeNull();

    fetchCentralOverview.mockClear();
    const select = screen
      .getByTestId("overview-inspect-eq")
      .querySelector("select");
    fireEvent.change(select!, { target: { value: "BOILER_1" } });

    await waitFor(() => {
      const last = vi.mocked(postInspect).mock.calls.at(-1)?.[0] as {
        equipment_ids: string[];
      };
      expect(last.equipment_ids).toEqual(["BOILER_1"]);
    });
    expect(screen.getByTestId("overview-charts-ready")).toBeTruthy();
    expect(screen.getByTestId("overview-econ-delta-plot")).toBeTruthy();
    expect(screen.getByTestId("overview-econ-mat-resid-plot")).toBeTruthy();
    expect(screen.getByTestId("overview-row-count").textContent).toContain(
      "35536",
    );
  });

  it("overlay select does not null building overview", async () => {
    renderOverview();
    fireEvent.click(
      screen.getByTestId("overview-refresh").querySelector("button")!,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-charts-ready")).toBeTruthy();
    });
    fireEvent.click(
      screen.getByTestId("overview-econ-overlay-exp").querySelector("button")!,
    );
    const overlay = screen
      .getByTestId("overview-econ-overlay-eq")
      .querySelector("select");
    expect(overlay).toBeTruthy();
    fireEvent.change(overlay!, { target: { value: "AHU_2" } });
    await waitFor(() => {
      expect(fetchCentralOverview).toHaveBeenCalled();
    });
    expect(screen.getByTestId("overview-charts-ready")).toBeTruthy();
    expect(screen.queryByTestId("overview-idle-hint")).toBeNull();
    expect(screen.getByTestId("overview-econ-mat-resid-plot")).toBeTruthy();
  });

  it("does not render an Overview equipment picker", async () => {
    renderOverview();
    await waitFor(() => {
      expect(screen.getByTestId("overview-idle-hint")).toBeTruthy();
    });
    expect(screen.queryByTestId("overview-equipment-select")).toBeNull();
  });
});
