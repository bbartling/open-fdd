import { describe, expect, it, vi, beforeEach } from "vitest";
import { fetchCentralOverview } from "./centralOverview";
import { AIR_BARE_MIN_OCC_HOURS_WEEK, RAINBOW_PALETTE } from "./plotlyTheme";

vi.mock("./analyticsApi", () => ({
  postRuntime: vi.fn(async () => ({
    schema_version: "1",
    query_version: "runtime-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: ["from historian"],
    rows: [
      {
        kind: "weekly_equipment",
        plant_group: "air",
        equipment_id: "AHU_1",
        label: "AHU_1 · fan-status",
        week_label: "2026-03-23",
        run_hours: 80,
        avg_oat_f: 45,
      },
      {
        kind: "weekly_equipment",
        plant_group: "air",
        equipment_id: "AHU_2",
        label: "AHU_2 · fan-status",
        week_label: "2026-03-23",
        run_hours: 70,
        avg_oat_f: 46,
      },
      {
        kind: "weekly_equipment",
        plant_group: "air",
        equipment_id: "AHU_1",
        label: "AHU_1 · fan-status",
        week_label: "2026-03-30",
        run_hours: 90,
        avg_oat_f: 50,
      },
      {
        kind: "weekly_equipment",
        plant_group: "air",
        equipment_id: "AHU_2",
        label: "AHU_2 · fan-status",
        week_label: "2026-03-30",
        run_hours: 85,
        avg_oat_f: 51,
      },
    ],
    equipment: [
      { equipment_id: "AHU_1", run_hours: 170, coverage_pct: 40, plant_group: "air" },
      { equipment_id: "AHU_2", run_hours: 155, coverage_pct: 38, plant_group: "air" },
      { equipment_id: "VAV_1", run_hours: 3, coverage_pct: 10 },
    ],
    points: [],
    skipped: [],
  })),
  postMechanicalCooling: vi.fn(async () => ({
    schema_version: "1",
    query_version: "mechanical-cooling-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        kind: "oat_bin",
        series_kind: "individual_device",
        equipment_id: "CHILLER_2",
        bin_lo_f: 65,
        bin_hi_f: 70,
        bin_label: "65-70",
        hours: 120,
      },
      {
        kind: "oat_bin",
        series_kind: "individual_device",
        equipment_id: "CHILLER_2",
        bin_lo_f: 70,
        bin_hi_f: 75,
        bin_label: "70-75",
        hours: 100,
      },
      {
        kind: "oat_bin",
        series_kind: "aggregate_device_hours",
        equipment_id: "ALL",
        bin_lo_f: 65,
        bin_hi_f: 70,
        bin_label: "65-70",
        hours: 120,
      },
      {
        kind: "oat_bin",
        series_kind: "aggregate_device_hours",
        equipment_id: "ALL",
        bin_lo_f: 70,
        bin_hi_f: 75,
        bin_label: "70-75",
        hours: 100,
      },
      {
        kind: "oat_bin",
        series_kind: "aggregate_active_hours",
        equipment_id: "ANY",
        bin_lo_f: 65,
        bin_hi_f: 70,
        bin_label: "65-70",
        hours: 120,
      },
      {
        kind: "oat_bin",
        series_kind: "aggregate_active_hours",
        equipment_id: "ANY",
        bin_lo_f: 70,
        bin_hi_f: 75,
        bin_label: "70-75",
        hours: 100,
      },
    ],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postEconomizer: vi.fn(async () => ({
    schema_version: "1",
    query_version: "economizer-diagnostics-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        equipment_id: "AHU_1",
        n_fan_on_samples: 100,
        n_identifiable: 50,
      },
    ],
    equipment: [],
    points: Array.from({ length: 8 }, (_, i) => ({
      equipment_id: "AHU_1",
      timestamp_utc: `2026-07-01T0${i}:00:00Z`,
      oat_f: 55 + i,
      rat_f: 72,
      mat_f: 65 + i * 0.5,
      damper_fb_pct: 40,
      delta_or_f: 55 + i - 72,
      delta_mr_f: 65 + i * 0.5 - 72,
      mat_resid_f: -1.5,
      identifiable: true,
      fan_on: true,
    })),
    skipped: [],
  })),
  postSchedule: vi.fn(async () => ({
    schema_version: "1",
    query_version: "schedule-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        equipment_id: "AHU_1",
        occupied_hours: 40,
        unoccupied_hours: 8,
      },
    ],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postBasVsWebOat: vi.fn(async () => ({
    schema_version: "1",
    query_version: "bas-vs-web-oat-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: ["BAS vs web OAT unavailable"],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  })),
}));

describe("fetchCentralOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("builds Overview payload from central DataFusion envelopes", async () => {
    const out = await fetchCentralOverview({
      building_id: "BUILDING_100",
      equipment: [
        { equipment_id: "AHU_1", equipment_type: "AHU" },
        { equipment_id: "VAV_1", equipment_type: "VAV" },
      ],
    });
    expect(out.ok).toBe(true);
    expect(out.source).toBe("central-datafusion");
    expect(out.motor_weekly.plants[0]?.figure?.data?.length).toBeGreaterThan(0);
    expect(out.mech_cooling.figure?.data?.length).toBeGreaterThan(0);
    expect(out.economizer_free_cooling.delta_scatter?.meta?.provenance).toMatch(
      /DataFusion/,
    );
    expect(out.economizer_free_cooling.delta_scatter?.layout?.title).toMatch(
      /delta scatter/i,
    );
    expect(out.economizer_free_cooling.mat_residual?.data?.length).toBeGreaterThan(
      0,
    );
    expect(out.economizer_free_cooling.temps_overlay?.layout?.title).toMatch(
      /Free-cooling temps/i,
    );
    expect(out.devices_by_type).toEqual([
      { type: "AHU", count: 1 },
      { type: "VAV", count: 1 },
    ]);
  });

  it("renders per-AHU weekly bars + OAT y2 + bare-min line (vibe19 parity)", async () => {
    const out = await fetchCentralOverview({ building_id: "BUILDING_100" });
    const air = out.motor_weekly.plants.find((p) => p.plant_group === "air");
    expect(air).toBeTruthy();
    const bars = (air!.figure?.data ?? []).filter((t) => t.type === "bar");
    expect(bars.length).toBeGreaterThanOrEqual(2);
    expect(bars.map((t) => t.name)).toEqual(
      expect.arrayContaining(["AHU_1 · fan-status", "AHU_2 · fan-status"]),
    );
    expect(bars[0]?.marker?.color).toBe(RAINBOW_PALETTE[0]);
    const oat = (air!.figure?.data ?? []).find((t) =>
      String(t.name).includes("Avg OAT"),
    );
    expect(oat?.yaxis).toBe("y2");
    expect(oat?.line).toMatchObject({ dash: "dot", color: "#333333" });
    const shapes = air!.figure?.layout?.shapes as Array<Record<string, unknown>>;
    expect(shapes?.[0]?.y0).toBe(AIR_BARE_MIN_OCC_HOURS_WEEK);
    // Section owns the title — figure should not duplicate plant H2.
    expect(air!.figure?.layout?.title).toBeUndefined();
  });

  it("stacks mech OAT bins per device and does not promote history_rows", async () => {
    const out = await fetchCentralOverview({ building_id: "BUILDING_100" });
    const fig = out.mech_cooling.figure!;
    const bar = fig.data.find((t) => t.type === "bar" && t.name === "CHILLER_2");
    expect(bar).toBeTruthy();
    expect(fig.data.some((t) => t.name === "Total compressor device-hours")).toBe(
      true,
    );
    expect(fig.data.some((t) => t.name === "Any compressor active")).toBe(true);
    expect(out.mech_cooling.callout).toMatch(/Only CHILLER_2/);
    expect(fig.layout?.barmode).toBe("stack");
  });
});

describe("mechFigure history_rows honesty", () => {
  it("returns null figure when only descriptive history_rows are present", async () => {
    const { postMechanicalCooling } = await import("./analyticsApi");
    vi.mocked(postMechanicalCooling).mockResolvedValueOnce({
      schema_version: "1",
      query_version: "mechanical-cooling-v1",
      generated_at: "",
      engine: "datafusion",
      warnings: ["descriptive"],
      rows: [
        { equipment_id: "AHU_1", history_rows: 1000 },
        { equipment_id: "VAV_1", history_rows: 500 },
      ],
      equipment: [],
      points: [],
      skipped: [],
    } as never);

    const out = await fetchCentralOverview({ building_id: "BUILDING_100" });
    expect(out.mech_cooling.figure).toBeNull();
    expect(out.mech_cooling.bins).toEqual([]);
    expect(out.mech_cooling.coverage.length).toBeGreaterThan(0);
    expect(out.mech_cooling.caption).toMatch(/No compressor×OAT|descriptive/i);
  });
});
