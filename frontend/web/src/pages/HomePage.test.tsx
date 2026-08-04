import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { HomePage } from "./HomePage";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    equipment: [
      {
        equipment_id: "AHU_1",
        equipment_type: "AHU",
        ok: true,
        sampling: {
          row_count: 100,
          first_timestamp: "2026-01-01T00:00:00Z",
          last_timestamp: "2026-02-01T00:00:00Z",
        },
        columns: [{ column: "sat", role: "sat", status: "mapped" }],
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: {} })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/analyticsApi", () => ({
  listFddEquipment: vi.fn(async () => [
    { equipment_id: "AHU_1", equipment_type: "AHU" },
    { equipment_id: "VAV_1", equipment_type: "VAV" },
  ]),
}));

vi.mock("../api/overviewOracleApi", () => ({
  fetchOverviewVibe19: vi.fn(async () => ({
    ok: true,
    building_id: "B1",
    source: "vibe19-pandas-oracle",
    elapsed_s: 0.1,
    equipment_count: 2,
    equipment_ids: ["AHU_1", "VAV_1"],
    has_weather: false,
    span: {
      start: "2026-01-01T00:00:00Z",
      end: "2026-02-01T00:00:00Z",
      span_hours: 744,
    },
    motor_weekly: {
      caption: "test",
      plants: [
        {
          plant_group: "air",
          title: "Air side — supply fans",
          caption: "c",
          figure: {
            data: [{ type: "bar", x: ["2026-01-06"], y: [10], name: "AHU_1" }],
            layout: { title: "Air" },
          },
          empty: false,
        },
      ],
      table: [{ week_label: "2026-01-06", hours: 10, plant_group: "air" }],
    },
    mech_cooling: {
      caption: "c",
      figure: {
        data: [{ type: "bar", x: ["30-35"], y: [2], name: "CHILLER_1" }],
        layout: {},
      },
      bins: [{ bin_label: "30-35", hours: 2 }],
      coverage: [{ Equipment: "CHILLER_1", Included: true }],
      n_included: 1,
      n_excluded: 0,
    },
    economizer_weather: {
      caption: "c",
      table: [{ equipment_id: "AHU_1", opportunity_hours: 12 }],
    },
    economizer_free_cooling: {
      caption: "c",
      metrics: [{ equipment_id: "AHU_1", fan_on_hours: 100 }],
      delta_scatter: {
        data: [{ type: "scatter", x: [10], y: [1], mode: "markers" }],
        layout: {},
      },
      mat_residual: null,
      temps_overlay: null,
      overlay_equipment_id: "AHU_1",
      skipped: [],
    },
    bas_vs_web_oat: {
      caption: "c",
      overlay: {
        data: [{ type: "scatter", x: ["t"], y: [50], name: "BAS OAT" }],
        layout: {},
      },
      histogram: null,
      oat_err: 5,
    },
    devices_by_type: [
      { type: "AHU", count: 1 },
      { type: "VAV", count: 1 },
    ],
  })),
  fetchOverviewInspect: vi.fn(async () => ({
    ok: true,
    equipment_id: "AHU_1",
    row_count: 100,
    plottable_columns: ["sat"],
    columns_plotted: ["sat"],
    first_timestamp: "2026-01-01T00:00:00Z",
    last_timestamp: "2026-02-01T00:00:00Z",
    span: "2026-01-01 → 2026-02-01",
    figure: {
      data: [{ type: "scatter", x: ["t"], y: [1], name: "sat" }],
      layout: {},
    },
    csv_preview: [{ sat: 1 }],
  })),
  downloadRowsCsv: vi.fn(),
}));

vi.mock("../api/fddApi", () => ({
  getFddStatus: vi.fn(async () => ({ rule_count: 59, rules_dir: "x", rules_dir_exists: true })),
  listFddRules: vi.fn(async () => []),
  getFddResults: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
  runFdd: vi.fn(async () => ({
    ok: true,
    results: [],
    total_ms: 12,
    rules_run: 0,
  })),
}));

vi.mock("../api/reportsApi", () => ({
  listReports: vi.fn(async () => []),
  createReportDraft: vi.fn(async () => ({ ok: true })),
  getEngineeringFindingsReport: vi.fn(async () => ({})),
}));

vi.mock("../api/cutoverApi", () => ({
  getUiGeneration: vi.fn(async () => ({ generation: "react" })),
}));

vi.mock("../api/uploadApi", () => ({
  uploadPackage: vi.fn(),
}));

import { apiFetch } from "../api/client";
import { listPackageBuildings } from "../api/mappingApi";
import { listFddEquipment } from "../api/analyticsApi";

describe("HomePage overview", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      contract: { contract_version: "1.0.0-test" },
      capabilities: { react_ui: true },
    });
    vi.mocked(listPackageBuildings).mockClear();
    vi.mocked(listFddEquipment).mockClear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("shows populated Overview analytics when authenticated with equipment", async () => {
    sessionStorage.setItem("openfdd.auth.token", "test-token");
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-populated")).toBeTruthy();
      expect(screen.getByTestId("overview-eq-count").textContent).toContain("2");
      expect(screen.getByTestId("overview-motor-runtime")).toBeTruthy();
      expect(screen.getByTestId("overview-schedule")).toBeTruthy();
    });
    expect(listPackageBuildings).toHaveBeenCalled();
    expect(listFddEquipment).toHaveBeenCalled();
  });

  it("shows Streamlit-oracle empty Overview and skips JWT inventory when anonymous", async () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("oracle-hero")).toBeTruthy();
      expect(screen.getByTestId("overview-start-here")).toBeTruthy();
    });
    expect(listPackageBuildings).not.toHaveBeenCalled();
    expect(listFddEquipment).not.toHaveBeenCalled();
    expect(screen.getByText("How it works")).toBeTruthy();
    expect(screen.getByTestId("sidebar-rule-tuning")).toBeTruthy();
  });
});
