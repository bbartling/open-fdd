import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { OverviewPopulated } from "./OverviewPopulated";

vi.mock("../api/fddApi", () => ({
  getFddStatus: vi.fn(async () => ({
    ok: true,
    rule_count: 1,
    rules_dir: "sql_rules",
    rules_dir_exists: true,
  })),
  listFddRules: vi.fn(async () => []),
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
        sampling: { row_count: 10 },
      },
      {
        equipment_id: "BOILER_1",
        equipment_type: "boiler",
        sampling: { row_count: 8 },
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: { params: {} } })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

const { emptyOverview } = vi.hoisted(() => ({
  emptyOverview: {
    ok: true,
    building_id: "B1",
    source: "test",
    elapsed_s: 0.1,
    equipment_count: 2,
    equipment_ids: ["AHU_1", "BOILER_1"],
    has_weather: false,
    span: { start: null, end: null },
    motor_weekly: { caption: "", plants: [], table: [] },
    mech_cooling: {
      caption: "",
      figure: null,
      bins: [],
      coverage: [],
      n_included: null,
      n_excluded: null,
    },
    economizer_weather: { caption: "", figure: null },
    economizer_free_cooling: {
      delta_scatter: null,
      mat_residual: null,
      temps_overlay: { data: [{ x: [1], y: [2], type: "scatter" }], layout: {} },
      metrics: [{ equipment_id: "AHU_1" }, { equipment_id: "AHU_2" }],
      overlay_equipment_id: "AHU_1",
    },
    bas_vs_web_oat: { overlay: null, histogram: null },
    schedule: {},
    devices_by_type: [],
    error: null,
  },
}));

vi.mock("../api/centralOverview", () => ({
  fetchCentralOverview: vi.fn(async () => emptyOverview),
}));

const { ALL_COLS } = vi.hoisted(() => ({
  ALL_COLS: [
    "sat",
    "rat",
    "mat",
    "oat",
    "fan_status",
    "oa_damper_pct",
    "clg_vlv",
    "htg_vlv",
    "sa_flow",
    "ra_flow",
  ],
}));

vi.mock("../api/analyticsApi", () => ({
  postInspect: vi.fn(async ({ equipment_ids }: { equipment_ids: string[] }) => ({
    coverage: {
      plottable_columns: ALL_COLS,
      columns_plotted: ALL_COLS,
      row_count: 2,
      first_timestamp: "2024-01-01T00:00:00Z",
      last_timestamp: "2024-01-01T01:00:00Z",
    },
    points: [
      {
        timestamp_utc: "2024-01-01T00:00:00Z",
        equipment_id: equipment_ids[0],
        ...Object.fromEntries(ALL_COLS.map((c) => [c, 1])),
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
import { fetchCentralOverview } from "../api/centralOverview";

const EQUIPMENT = [
  { equipment_id: "AHU_1", equipment_type: "AHU" },
  { equipment_id: "AHU_10", equipment_type: "AHU" },
  { equipment_id: "BOILER_1", equipment_type: "boiler" },
];

function renderOverview(
  equipmentId = "AHU_1",
  onEquipmentChange = vi.fn(),
) {
  return render(
    <MemoryRouter>
      <OverviewPopulated
        buildingId="B1"
        equipmentId={equipmentId}
        equipment={EQUIPMENT}
        unitSystem="imperial"
        onEquipmentChange={onEquipmentChange}
      />
    </MemoryRouter>,
  );
}

describe("OverviewPopulated inspect equipment", () => {
  beforeEach(() => {
    vi.mocked(postInspect).mockClear();
    vi.mocked(fetchCentralOverview).mockClear();
  });

  it("has no empty equipment option", async () => {
    renderOverview();
    await waitFor(() => {
      expect(screen.getByTestId("overview-equipment-select")).toBeTruthy();
    });
    const select = screen
      .getByTestId("overview-equipment-select")
      .querySelector("select")!;
    const values = [...select.options].map((o) => o.value);
    expect(values).not.toContain("");
    expect(values[0]).toBe("AHU_1");
    expect(values.indexOf("AHU_1")).toBeLessThan(values.indexOf("AHU_10"));
  });

  it("auto-loads inspect with all plottable columns", async () => {
    renderOverview();
    await waitFor(() => {
      expect(postInspect).toHaveBeenCalled();
    });
    const req = vi.mocked(postInspect).mock.calls.at(-1)?.[0] as {
      equipment_ids: string[];
      series?: { columns?: string[] };
    };
    expect(req.equipment_ids).toEqual(["AHU_1"]);
    expect(req.series?.columns).toBeUndefined();
    await waitFor(() => {
      const cols = screen.getByTestId("overview-inspect-cols-select");
      const selected = [...cols.querySelectorAll("option")].filter(
        (o) => (o as HTMLOptionElement).selected,
      );
      expect(selected.map((o) => o.value)).toEqual(ALL_COLS);
    });
  });

  it("refetches all inspect columns when top equipment changes", async () => {
    const onEquipmentChange = vi.fn();
    const { rerender } = render(
      <MemoryRouter>
        <OverviewPopulated
          buildingId="B1"
          equipmentId="AHU_1"
          equipment={EQUIPMENT}
          unitSystem="imperial"
          onEquipmentChange={onEquipmentChange}
        />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(postInspect).toHaveBeenCalled();
    });
    vi.mocked(postInspect).mockClear();
    rerender(
      <MemoryRouter>
        <OverviewPopulated
          buildingId="B1"
          equipmentId="BOILER_1"
          equipment={EQUIPMENT}
          unitSystem="imperial"
          onEquipmentChange={onEquipmentChange}
        />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(postInspect).toHaveBeenCalled();
      const last = vi.mocked(postInspect).mock.calls.at(-1)?.[0] as {
        equipment_ids: string[];
        series?: { columns?: string[] };
      };
      expect(last.equipment_ids).toEqual(["BOILER_1"]);
      expect(last.series?.columns).toBeUndefined();
    });
  });

  it("refetches inspect when CSV/equipment select changes", async () => {
    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId("overview-inspect-eq")).toBeTruthy();
      expect(postInspect).toHaveBeenCalled();
    });
    vi.mocked(postInspect).mockClear();

    const select = screen
      .getByTestId("overview-inspect-eq")
      .querySelector("select");
    expect(select).toBeTruthy();
    fireEvent.change(select!, { target: { value: "BOILER_1" } });

    await waitFor(() => {
      expect(postInspect).toHaveBeenCalled();
      const last = vi.mocked(postInspect).mock.calls.at(-1)?.[0] as {
        equipment_ids: string[];
      };
      expect(last.equipment_ids).toEqual(["BOILER_1"]);
    });
  });

  it("does not wipe building charts when overlay AHU changes", async () => {
    renderOverview();
    await waitFor(() => {
      expect(
        screen.getByTestId("overview-refresh").querySelector("button")?.disabled,
      ).toBe(false);
    });
    fireEvent.click(
      screen.getByTestId("overview-refresh").querySelector("button")!,
    );
    await waitFor(() => {
      expect(fetchCentralOverview).toHaveBeenCalled();
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
    // Overlay refresh may set loading, but must not null the overview payload.
    expect(screen.queryByTestId("overview-idle-hint")).toBeNull();
    expect(screen.getByTestId("overview-motor-runtime")).toBeTruthy();
    expect(screen.getByText(/2 equip/)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("overview-charts-ready")).toBeTruthy();
    });
  });
});
