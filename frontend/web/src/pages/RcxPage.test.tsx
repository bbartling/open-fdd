import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { RcxPage } from "./RcxPage";
import {
  RCX_FAMILY_MIN_COUNTS,
  REQUIRED_RCX_PRESET_IDS,
} from "../nav/rcxCatalog";

const ALL_PRESETS = [
  { id: "zone_comfort_rank", title: "Zones rank", family: "Zones / VAV", chart: "ranking", frozen: true },
  { id: "zone_temps", title: "Zones temps", family: "Zones / VAV", chart: "timeseries", frozen: true },
  { id: "vav_flows", title: "VAV flows", family: "Zones / VAV", chart: "timeseries", frozen: true },
  { id: "vav_health_matrix", title: "VAV health", family: "Zones / VAV", chart: "vav_health", frozen: false },
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
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/analyticsApi", () => ({
  listRcxPresets: vi.fn(async () => ALL_PRESETS),
  postRuntime: vi.fn(async () => ({
    schema_version: "1",
    query_version: "motor-weekly-runtime",
    generated_at: "",
    engine: "timescale-sql",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  })),
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

import { listRcxPresets, postRcxPreset, postRuntime } from "../api/analyticsApi";
import { getSessionConfig, listPackageBuildings } from "../api/mappingApi";

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="loc">{location.search}</span>;
}

function presetValues(): string[] {
  const select = screen.getByTestId("rcx-preset").querySelector("select");
  return [...(select?.options ?? [])].map((option) => option.value);
}

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
    expect(listRcxPresets).toHaveBeenCalledWith(
      "BUILDING_100",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByTestId("rcx-comfort-donut")).toBeTruthy();
    expect(screen.getByTestId("rcx-companion-note").textContent).toMatch(
      /Worst-zones timeseries/,
    );
  });

  it("opening a preset uses the cache and Refresh RCx preset recomputes", async () => {
    render(
      <MemoryRouter initialEntries={["/rcx?site=BUILDING_100"]}>
        <RcxPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(postRcxPreset).toHaveBeenCalled();
    });
    const opened = vi.mocked(postRcxPreset).mock.calls[0]?.[0] as { refresh?: boolean };
    expect(opened.refresh).toBeUndefined();
    const calls = vi.mocked(postRcxPreset).mock.calls.length;
    fireEvent.click(screen.getByTestId("rcx-run").querySelector("button")!);
    await waitFor(() => {
      expect(vi.mocked(postRcxPreset).mock.calls.length).toBe(calls + 1);
    });
    const forced = vi.mocked(postRcxPreset).mock.calls.at(-1)?.[0] as {
      refresh?: boolean;
    };
    expect(forced.refresh).toBe(true);
  });

  it("renders vav_health_matrix from rows when points are empty", async () => {
    const zonesFirst = [
      {
        id: "vav_health_matrix",
        title: "VAV health",
        family: "Zones / VAV",
        chart: "vav_health",
        frozen: false,
      },
      ...ALL_PRESETS.filter((p) => p.id !== "vav_health_matrix"),
    ];
    vi.mocked(listRcxPresets).mockResolvedValueOnce(zonesFirst);
    vi.mocked(postRcxPreset).mockResolvedValueOnce({
      schema_version: "1",
      query_version: "vav-health-v1",
      generated_at: "",
      engine: "datafusion",
      warnings: [],
      coverage: {
        chart_kind: "vav_health",
        schema_version: "vav_health_matrix_v1",
        title: "VAV health",
        family: "Zones / VAV",
      },
      rows: [
        {
          equipment_id: "TERM_A",
          broken_box: true,
          poor_zone_performance: false,
          rogue_damper: false,
          comfort_fault_h: 22,
        },
        {
          equipment_id: "TERM_B",
          broken_box: false,
          poor_zone_performance: true,
          rogue_damper: false,
          comfort_fault_h: 8,
        },
        {
          equipment_id: "TERM_C",
          broken_box: null,
          poor_zone_performance: false,
          rogue_damper: false,
          comfort_fault_h: 0,
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
    } as Awaited<ReturnType<typeof postRcxPreset>>);

    render(
      <MemoryRouter initialEntries={["/rcx?site=BUILDING_100"]}>
        <RcxPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(postRcxPreset).toHaveBeenCalledWith(
        expect.objectContaining({
          series: expect.objectContaining({ preset_id: "vav_health_matrix" }),
        }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId("rcx-error")).toBeNull();
      expect(screen.getByTestId("rcx-plot")).toBeTruthy();
      expect(screen.getByTestId("rcx-comfort-donut")).toBeTruthy();
      expect(screen.getByTestId("rcx-rows-table")).toBeTruthy();
    });
    expect(screen.getByTestId("rcx-companion-note").textContent).toMatch(
      /Broken-box flags unknown/,
    );
    expect(screen.queryByTestId("rcx-plot-preview-table")).toBeNull();
  });

  it("previews the newest samples on a timeseries preset", async () => {
    const tempsFirst = [
      {
        id: "zone_temps",
        title: "Zones temps",
        family: "Zones / VAV",
        chart: "timeseries",
        frozen: true,
      },
      ...ALL_PRESETS.filter((p) => p.id !== "zone_temps"),
    ];
    vi.mocked(listRcxPresets).mockResolvedValueOnce(tempsFirst);
    const points = Array.from({ length: 12 }, (_, i) => ({
      equipment_id: "VAV_1",
      timestamp_utc: `2024-06-01T00:${String(i).padStart(2, "0")}:00Z`,
      value_f: 70 + i,
      series: "primary",
    }));
    vi.mocked(postRcxPreset).mockResolvedValueOnce({
      schema_version: "1",
      query_version: "rcx-preset-zone_temps-v1",
      generated_at: "",
      engine: "datafusion",
      warnings: [],
      coverage: {
        chart_kind: "timeseries",
        title: "Zones temps",
        family: "Zones / VAV",
        role_col: "zone_t",
      },
      rows: [],
      equipment: [],
      points,
      skipped: [],
    });

    render(
      <MemoryRouter initialEntries={["/rcx?site=BUILDING_100"]}>
        <RcxPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("rcx-plot-preview-table").querySelector("tbody td")
          ?.textContent,
      ).toBe("2024-06-01T00:11:00Z");
    });
    const select = screen
      .getByTestId("rcx-plot-preview-rows")
      .querySelector("select");
    expect(select?.value).toBe("10");
    expect(
      screen.getByTestId("rcx-plot-preview-table").querySelectorAll("tbody tr"),
    ).toHaveLength(10);
    expect(screen.queryByText(/first rows/i)).toBeNull();
    fireEvent.change(select!, { target: { value: "500" } });
    expect(
      screen.getByTestId("rcx-plot-preview-table").querySelectorAll("tbody tr"),
    ).toHaveLength(12);
    expect(
      screen.getByTestId("rcx-plot-preview-table").querySelector("tbody td")
        ?.textContent,
    ).toBe("2024-06-01T00:11:00Z");
  });

  it("reports weekly observations and the saved schedule reference together", async () => {
    vi.mocked(listRcxPresets).mockResolvedValueOnce([
      {
        id: "ahu_motor_weekly",
        title: "Weekly runtime",
        family: "AHU / air",
        chart: "bar",
        frozen: true,
      },
      ...ALL_PRESETS,
    ]);
    vi.mocked(getSessionConfig).mockResolvedValue({
      ok: true,
      config: {
        schema_version: "openfdd.session.v1",
        occupancy_schedule: {
          timezone: "America/Chicago",
          nominal_occ_hours_week: 60,
          days: {
            mon: { occupied: true, start: "07:00", end: "17:00" },
            tue: { occupied: true, start: "07:00", end: "17:00" },
            wed: { occupied: true, start: "07:00", end: "17:00" },
            thu: { occupied: true, start: "07:00", end: "17:00" },
            fri: { occupied: false, start: "07:00", end: "17:00" },
          },
        },
      },
    });
    vi.mocked(postRuntime).mockResolvedValue({
      schema_version: "1",
      query_version: "motor-weekly-runtime",
      generated_at: "",
      engine: "timescale-sql",
      warnings: [],
      rows: [
        {
          equipment_id: "AHU_A",
          kind: "motor",
          plant_group: "ahu",
          week_label: "2026-W23",
          week_start: "2026-06-01T00:00:00Z",
          run_hours: 40,
          n_observations: 18,
          partial_week: false,
          avg_oat_f: 70,
        },
        {
          equipment_id: "AHU_B",
          kind: "motor",
          plant_group: "ahu",
          week_label: "2026-W23",
          week_start: "2026-06-01T00:00:00Z",
          run_hours: 12,
          n_observations: 18,
          partial_week: false,
          avg_oat_f: 71,
        },
        {
          equipment_id: "AHU_A",
          kind: "motor",
          plant_group: "ahu",
          week_label: "2026-W24",
          week_start: "2026-06-08T00:00:00Z",
          run_hours: 3,
          n_observations: 6,
          partial_week: true,
          avg_oat_f: 75,
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
    } as Awaited<ReturnType<typeof postRuntime>>);
    render(
      <MemoryRouter initialEntries={["/rcx?site=BUILDING_100"]}>
        <RcxPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("rcx-family").querySelector("select")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("rcx-family").querySelector("select")!, {
      target: { value: "AHU / air" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("rcx-provenance").textContent).toContain(
        "weekly observations 3",
      );
    });
    const provenance = screen.getByTestId("rcx-provenance").textContent ?? "";
    expect(provenance).toContain("samples 42");
    expect(provenance).toContain(
      "schedule 40 h/week (America/Chicago, session openfdd.session.v1)",
    );
    expect(provenance).not.toContain("points=0");
    expect(provenance).not.toContain("60 h/week");
  });

  it("runs one preset query per selection", async () => {
    render(
      <MemoryRouter initialEntries={["/rcx?site=BUILDING_100"]}>
        <RcxPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(vi.mocked(postRcxPreset).mock.calls.length).toBe(1);
    });
    const select = screen.getByTestId("rcx-preset").querySelector("select");
    fireEvent.change(select!, { target: { value: "zone_temps" } });
    await waitFor(() => {
      expect(vi.mocked(postRcxPreset).mock.calls.length).toBe(2);
    });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(vi.mocked(postRcxPreset).mock.calls.length).toBe(2);
    const ids = vi.mocked(postRcxPreset).mock.calls.map(
      (call) =>
        (call[0] as { series?: { preset_id?: string } }).series?.preset_id,
    );
    expect(ids).toEqual(["zone_comfort_rank", "zone_temps"]);
  });

  it("commits only the latest site when a previous preset response arrives late", async () => {
    const lists = new Map<string, ReturnType<typeof deferred<typeof ALL_PRESETS>>>();
    const runs = new Map<string, ReturnType<typeof deferred<Awaited<ReturnType<typeof postRcxPreset>>>>>();
    vi.mocked(listPackageBuildings).mockResolvedValue(["SITE_A", "SITE_B"]);
    vi.mocked(listRcxPresets).mockImplementation(async (site?: string) => {
      const slot = deferred<typeof ALL_PRESETS>();
      lists.set(String(site), slot);
      return slot.promise;
    });
    vi.mocked(postRcxPreset).mockImplementation(async (body: { building_id?: string }) => {
      const slot = deferred<Awaited<ReturnType<typeof postRcxPreset>>>();
      runs.set(String(body.building_id), slot);
      return slot.promise;
    });

    render(
      <MemoryRouter initialEntries={["/rcx?site=SITE_A"]}>
        <LocationProbe />
        <RcxPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(lists.has("SITE_A")).toBe(true);
    });
    lists.get("SITE_A")!.resolve([
      {
        id: "only_a",
        title: "Only A",
        family: "Zones / VAV",
        chart: "timeseries",
        frozen: true,
      },
    ]);
    await waitFor(() => {
      expect(runs.has("SITE_A")).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByTestId("sidebar-active-site")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("sidebar-active-site"), {
      target: { value: "SITE_B" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("loc").textContent).toContain("site=SITE_B");
    });
    await waitFor(() => {
      expect(lists.has("SITE_B")).toBe(true);
    });
    lists.get("SITE_B")!.resolve([
      {
        id: "only_b",
        title: "Only B",
        family: "Zones / VAV",
        chart: "timeseries",
        frozen: true,
      },
    ]);
    await waitFor(() => {
      expect(runs.has("SITE_B")).toBe(true);
    });
    runs.get("SITE_B")!.resolve({
      schema_version: "1",
      query_version: "rcx-b",
      generated_at: "",
      engine: "timescale",
      warnings: ["SITE_B_MARKER"],
      coverage: {
        chart_kind: "timeseries",
        title: "Only B",
        family: "Zones / VAV",
        preset_id: "only_b",
      },
      rows: [],
      equipment: [],
      points: [
        {
          equipment_id: "EQ_B",
          timestamp_utc: "2024-01-01T00:00:00Z",
          value_f: 2,
          series: "primary",
        },
      ],
      skipped: [],
    });
    await waitFor(() => {
      expect(screen.getByTestId("rcx-provenance").textContent).toContain(
        "SITE_B_MARKER",
      );
    });
    runs.get("SITE_A")!.resolve({
      schema_version: "1",
      query_version: "rcx-a",
      generated_at: "",
      engine: "timescale",
      warnings: ["SITE_A_MARKER"],
      coverage: {
        chart_kind: "timeseries",
        title: "Only A",
        family: "Zones / VAV",
        preset_id: "only_a",
      },
      rows: [],
      equipment: [],
      points: [
        {
          equipment_id: "EQ_A",
          timestamp_utc: "2024-01-01T00:00:00Z",
          value_f: 9,
          series: "primary",
        },
      ],
      skipped: [],
    });
    lists.get("SITE_A")!.resolve([
      {
        id: "only_a",
        title: "Only A",
        family: "Zones / VAV",
        chart: "timeseries",
        frozen: true,
      },
    ]);
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(screen.getByTestId("rcx-provenance").textContent).toContain("SITE_B_MARKER");
    expect(screen.getByTestId("rcx-provenance").textContent).not.toContain(
      "SITE_A_MARKER",
    );
    expect(presetValues()).toContain("only_b");
    expect(presetValues()).not.toContain("only_a");
    const siteB = vi.mocked(postRcxPreset).mock.calls.filter(
      (call) => (call[0] as { building_id?: string }).building_id === "SITE_B",
    );
    expect(siteB).toHaveLength(1);
    expect(
      (siteB[0]?.[0] as { series?: { preset_id?: string } }).series?.preset_id,
    ).toBe("only_b");
  });
});
