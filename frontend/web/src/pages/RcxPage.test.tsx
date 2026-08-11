import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { RcxPage } from "./RcxPage";
import {
  RCX_FAMILY_MIN_COUNTS,
  REQUIRED_RCX_PRESET_IDS,
} from "../nav/rcxCatalog";

const ALL_PRESETS = [
  { id: "zone_comfort_rank", title: "Zones rank", family: "Zones / VAV", chart: "ranking", frozen: true },
  { id: "zone_temps", title: "Zones temps", family: "Zones / VAV", chart: "timeseries", frozen: true },
  { id: "vav_flows", title: "VAV flows", family: "Zones / VAV", chart: "timeseries", frozen: true },
  { id: "ahu_dats", title: "AHU DAT", family: "AHU / air", chart: "timeseries", frozen: true },
  { id: "ahu_mats", title: "AHU MAT", family: "AHU / air", chart: "timeseries", frozen: true },
  { id: "ahu_rats", title: "AHU RAT", family: "AHU / air", chart: "timeseries", frozen: true },
  { id: "ahu_dampers", title: "AHU dampers", family: "AHU / air", chart: "timeseries", frozen: true },
  { id: "fan_speeds", title: "Fan speeds", family: "AHU / air", chart: "timeseries", frozen: true },
  { id: "duct_static_box", title: "Duct box", family: "AHU / air", chart: "box", frozen: true },
  { id: "duct_static_ts", title: "Duct ts", family: "AHU / air", chart: "timeseries", frozen: true },
  { id: "ahu_sat_reset_scatter", title: "SAT scatter", family: "AHU / air", chart: "scatter_oat", frozen: true },
  { id: "hw_reset_scatter", title: "HW scatter", family: "Boiler / HW", chart: "scatter_oat", frozen: true },
  { id: "chw_reset_scatter", title: "CHW scatter", family: "Chiller / CHW / tower", chart: "scatter_oat", frozen: true },
  { id: "cw_reset_scatter", title: "CW scatter", family: "Chiller / CHW / tower", chart: "scatter_oat", frozen: true },
  { id: "chw_temps_ts", title: "CHW temps", family: "Chiller / CHW / tower", chart: "timeseries", frozen: true },
  { id: "cw_temps_ts", title: "CW temps", family: "Chiller / CHW / tower", chart: "timeseries", frozen: true },
  { id: "meter_elec_cdd", title: "Elec CDD", family: "Metering", chart: "metering", frozen: true },
  { id: "meter_gas_hdd", title: "Gas HDD", family: "Metering", chart: "metering", frozen: true },
];

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["BUILDING_100"]),
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    equipment: [],
  })),
}));

vi.mock("../api/analyticsApi", () => ({
  listRcxPresets: vi.fn(async () => ALL_PRESETS),
  postRcxPreset: vi.fn(async () => ({
    schema_version: "1",
    query_version: "rcx-preset-zone_comfort_rank-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    coverage: { chart_kind: "ranking", title: "Zones rank", family: "Zones / VAV" },
    rows: [
      { equipment_id: "VAV_1", n_samples: 10, n_fail: 4, fail_pct: 40 },
    ],
    equipment: [],
    points: [{ equipment_id: "VAV_1", value_f: 40, series: "fail_pct" }],
    skipped: [],
  })),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

import { listRcxPresets, postRcxPreset } from "../api/analyticsApi";

describe("RcxPage vibe19 catalog", () => {
  beforeEach(() => {
    vi.mocked(listRcxPresets).mockClear();
    vi.mocked(postRcxPreset).mockClear();
  });

  it("lists every REQUIRED_RCX_PRESET_IDS id and family floors", () => {
    const ids = new Set(ALL_PRESETS.map((p) => p.id));
    for (const id of REQUIRED_RCX_PRESET_IDS) {
      expect(ids.has(id)).toBe(true);
    }
    for (const [family, min] of Object.entries(RCX_FAMILY_MIN_COUNTS)) {
      const n = ALL_PRESETS.filter((p) => p.family === family).length;
      expect(n).toBeGreaterThanOrEqual(min);
    }
  });

  it("locks site, orders Zones first, auto-runs, no building select", async () => {
    render(
      <MemoryRouter initialEntries={["/rcx?site=BUILDING_100"]}>
        <RcxPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("locked-site").textContent).toMatch(
        /zip:BUILDING_100/,
      );
    });
    expect(screen.queryByTestId("rcx-building")).toBeNull();
    const familySelect = screen.getByTestId("rcx-family").querySelector("select");
    const labels = [...(familySelect?.options ?? [])].map((o) => o.text);
    expect(labels[0]).toBe("Zones / VAV");
    expect(labels).toContain("Heat pump");
    expect(labels).toContain("Weather");
    await waitFor(() => {
      expect(postRcxPreset).toHaveBeenCalled();
    });
    expect(screen.getByTestId("rcx-comfort-donut")).toBeTruthy();
    expect(screen.getByTestId("rcx-companion-note").textContent).toMatch(
      /Worst-zones timeseries/,
    );
  });
});
