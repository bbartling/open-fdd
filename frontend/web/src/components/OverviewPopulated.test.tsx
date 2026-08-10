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

const emptyOverview = {
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
    temps_overlay: null,
  },
  bas_vs_web_oat: { overlay: null, histogram: null },
  schedule: {},
  devices_by_type: [],
  error: null,
};

vi.mock("../api/centralOverview", () => ({
  fetchCentralOverview: vi.fn(async () => emptyOverview),
}));

vi.mock("../api/analyticsApi", () => ({
  postInspect: vi.fn(async ({ equipment_ids }: { equipment_ids: string[] }) => ({
    coverage: {
      plottable_columns: ["sat"],
      columns_plotted: ["sat"],
      row_count: 2,
      first_timestamp: "2024-01-01T00:00:00Z",
      last_timestamp: "2024-01-01T01:00:00Z",
    },
    points: [
      {
        timestamp_utc: "2024-01-01T00:00:00Z",
        equipment_id: equipment_ids[0],
        sat: 55,
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

describe("OverviewPopulated inspect equipment", () => {
  beforeEach(() => {
    vi.mocked(postInspect).mockClear();
  });

  it("refetches inspect when CSV/equipment select changes", async () => {
    render(
      <MemoryRouter>
        <OverviewPopulated
          buildingId="B1"
          equipmentId="AHU_1"
          equipment={[
            { equipment_id: "AHU_1", equipment_type: "AHU" },
            { equipment_id: "BOILER_1", equipment_type: "boiler" },
          ]}
          unitSystem="imperial"
          onEquipmentChange={vi.fn()}
        />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("overview-inspect-eq")).toBeTruthy();
    });

    fireEvent.click(
      screen.getByTestId("overview-refresh").querySelector("button")!,
    );
    await waitFor(() => {
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
});
