import { describe, expect, it, vi, beforeEach } from "vitest";
import { fetchCentralOverview } from "./centralOverview";

vi.mock("./analyticsApi", () => ({
  postRuntime: vi.fn(async () => ({
    schema_version: "1",
    query_version: "runtime-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: ["from historian"],
    rows: [
      { equipment_id: "AHU_1", run_hours: 12.5, coverage_pct: 40 },
      { equipment_id: "VAV_1", run_hours: 3, coverage_pct: 10 },
    ],
    equipment: [
      { equipment_id: "AHU_1", run_hours: 12.5, coverage_pct: 40 },
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
    rows: [{ equipment_id: "CHILLER_1", history_rows: 500 }],
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
});
