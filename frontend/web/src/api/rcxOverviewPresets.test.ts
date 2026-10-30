import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadOverviewRcxPreset } from "./rcxOverviewPresets";

vi.mock("./mappingApi", () => ({
  getPackageMapping: vi.fn(async () => ({ ok: true, equipment: [] })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: {} })),
}));

vi.mock("./analyticsApi", () => ({
  postRuntime: vi.fn(),
  postEconomizer: vi.fn(),
  postMechanicalCooling: vi.fn(),
  postBasVsWebOat: vi.fn(),
}));

const envelope = {
  schema_version: "analytics-envelope-v1",
  query_version: "v",
  generated_at: "2026-06-01T00:00:00Z",
  engine: "timescale-sql",
  warnings: [] as string[],
  equipment: [],
  points: [],
  skipped: [],
};

describe("RCx overview presets normalize row-only envelopes before charts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("plots qualified economizer rows and explains rows that are not qualified", async () => {
    const { postEconomizer } = await import("./analyticsApi");
    vi.mocked(postEconomizer).mockResolvedValueOnce({
      ...envelope,
      rows: Array.from({ length: 6 }, (_, i) => ({
        ts: `2026-06-01T0${i}:00:00Z`,
        equipment_id: "SYN_AHU_E",
        oa_t: 50,
        rat: 72,
        mat: 60,
        sat: 55,
        oa_damper_pct: 40,
        delta_or_c: -22,
        delta_mr_c: -12,
        fan_on: true,
      })),
    } as never);
    const plotted = await loadOverviewRcxPreset("SYN_SITE", "economizer_delta");
    expect(plotted.figure).toBeTruthy();
    expect(plotted.error).toBeUndefined();
    expect(plotted.env.points.every((p) => p.identifiable === true)).toBe(true);
    expect(plotted.env.points[0]?.fan_on).toBe(true);

    vi.mocked(postEconomizer).mockResolvedValueOnce({
      ...envelope,
      rows: [
        {
          ts: "2026-06-01T01:00:00Z",
          equipment_id: "SYN_AHU_E",
          oa_t: 50,
          rat: 72,
          mat: 60,
          delta_or_c: -22,
          delta_mr_c: -12,
          fan_on: false,
        },
        {
          ts: "2026-06-01T02:00:00Z",
          equipment_id: "SYN_AHU_E",
          oa_t: 70,
          rat: 72,
          mat: 71,
          delta_or_c: -2,
          delta_mr_c: -1,
          fan_on: true,
        },
        {
          ts: "2026-06-01T03:00:00Z",
          equipment_id: "SYN_AHU_E",
          fan_on: true,
          delta_or_c: -22,
          delta_mr_c: -12,
        },
      ],
    } as never);
    const rejected = await loadOverviewRcxPreset("SYN_SITE", "economizer_delta");
    expect(rejected.figure).toBeNull();
    expect(rejected.error).toMatch(/not qualified|Fan-on|MAT/);
    expect(rejected.env.points.every((p) => p.identifiable !== true)).toBe(true);
  });

  it("plots runtime, mechanical-cooling, and BAS rows and explains empty results", async () => {
    const { postRuntime, postMechanicalCooling, postBasVsWebOat } = await import(
      "./analyticsApi"
    );
    vi.mocked(postRuntime).mockResolvedValueOnce({
      ...envelope,
      rows: [
        {
          equipment_id: "SYN_AHU_E",
          kind: "motor",
          plant_group: "ahu",
          week_label: "2026-W23",
          run_hours: 12,
        },
      ],
    } as never);
    const runtime = await loadOverviewRcxPreset("SYN_SITE", "ahu_motor_weekly");
    expect(runtime.figure).toBeTruthy();
    expect(runtime.error).toBeUndefined();
    expect(runtime.env.points).toEqual([]);
    expect(runtime.figure?.meta?.weekly_observations).toBe(1);
    expect(runtime.figure?.meta?.provenance).toContain("schedule 50 h/week (default)");
    expect(runtime.figure?.meta?.schedule_hours).toBe(50);

    vi.mocked(postRuntime).mockResolvedValueOnce({ ...envelope, rows: [] } as never);
    const runtimeEmpty = await loadOverviewRcxPreset("SYN_SITE", "ahu_motor_weekly");
    expect(runtimeEmpty.figure).toBeNull();
    expect(runtimeEmpty.error).toMatch(/motor weekly/);

    vi.mocked(postMechanicalCooling).mockResolvedValueOnce({
      ...envelope,
      rows: [
        {
          kind: "oat_bin",
          equipment_id: "SYN_CH",
          oat_bin: "60-70",
          run_hours: 4,
        },
      ],
    } as never);
    const mech = await loadOverviewRcxPreset("SYN_SITE", "mech_cooling_oat_bins");
    expect(mech.figure).toBeTruthy();
    expect(mech.env.rows[0]?.bin_label).toBe("60-70");
    expect(mech.env.rows[0]?.hours).toBe(4);

    vi.mocked(postMechanicalCooling).mockResolvedValueOnce({
      ...envelope,
      rows: [],
    } as never);
    const mechEmpty = await loadOverviewRcxPreset("SYN_SITE", "mech_cooling_oat_bins");
    expect(mechEmpty.figure).toBeNull();
    expect(mechEmpty.error).toMatch(/outdoor-air bins/);

    vi.mocked(postBasVsWebOat).mockResolvedValueOnce({
      ...envelope,
      rows: [
        {
          ts: "2026-06-01T12:00:00Z",
          equipment_id: "SYN_AHU_E",
          bas_oa_t: 50,
          web_oa_t: 48,
          delta_c: 2,
        },
      ],
    } as never);
    const bas = await loadOverviewRcxPreset("SYN_SITE", "bas_vs_web_oat");
    expect(bas.figure).toBeTruthy();
    expect(bas.env.points[0]?.bas_oat_c).toBe(50);
    expect(bas.env.points[0]?.web_oat_c).toBe(48);

    vi.mocked(postBasVsWebOat).mockResolvedValueOnce({ ...envelope, rows: [] } as never);
    const basEmpty = await loadOverviewRcxPreset("SYN_SITE", "bas_vs_web_oat");
    expect(basEmpty.figure).toBeNull();
    expect(basEmpty.error).toMatch(/BAS and web/);
  });
});
