import { describe, expect, it } from "vitest";
import chartContract from "./charts.contract.json";
import {
  basOverlay,
  econDeltaScatter,
  econTempsOverlay,
  mechFigure,
  weeklyPlantFigures,
} from "./centralOverview";
import { ruleResultChart } from "./vibeCharts";
import {
  normalizeTipOverviewEnvelope,
  tipOatBinLo,
} from "./tipAnalyticsNormalize";

/**
 * Soft-OPEN C4 known answers — synthetic tip Timescale envelopes → Plotly
 * contracts for Overview / FDD / RCx. Random synthetic ids only.
 */

describe("tipOatBinLo", () => {
  it("orders tip oat_bin labels", () => {
    expect(tipOatBinLo("<50")).toBeLessThan(tipOatBinLo("50-60"));
    expect(tipOatBinLo("50-60")).toBeLessThan(tipOatBinLo("60-70"));
    expect(tipOatBinLo("80-90")).toBeLessThan(tipOatBinLo(">=90"));
  });
});

describe("C4 tip Overview known answers", () => {
  it("runtime tip rows drive weekly plant bars (ahu→air)", () => {
    const env = normalizeTipOverviewEnvelope("runtime", {
      schema_version: "analytics-envelope-v1",
      query_version: "runtime-v1",
      generated_at: "2026-04-08T00:00:00Z",
      engine: "timescale-sql",
      warnings: [],
      rows: [
        {
          equipment_id: "SYN_AHU_A",
          kind: "motor",
          plant_group: "ahu",
          week_label: "2026-W14",
          run_hours: 42,
          runtime_hours: 42,
        },
        {
          equipment_id: "SYN_AHU_B",
          kind: "motor",
          plant_group: "ahu",
          week_label: "2026-W14",
          run_hours: 30,
          runtime_hours: 30,
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
      query_id: "runtime",
    });
    expect(env.rows.every((r) => r.kind === "weekly_equipment")).toBe(true);
    expect(env.rows.every((r) => r.plant_group === "air")).toBe(true);
    const plants = weeklyPlantFigures(env.rows);
    expect(plants).toHaveLength(1);
    expect(plants[0]?.plant_group).toBe("air");
    const bars = (plants[0]?.figure?.data ?? []).filter((t) => t.type === "bar");
    expect(bars.length).toBeGreaterThanOrEqual(2);
    const hours = bars.flatMap((t) => (t.y ?? []) as Array<number | null>);
    expect(hours).toEqual(expect.arrayContaining([42, 30]));
  });

  it("mechanical-cooling tip oat_bin rows drive stacked mech figure", () => {
    const env = normalizeTipOverviewEnvelope("mechanical-cooling", {
      schema_version: "analytics-envelope-v1",
      query_version: "mechanical-cooling-v1",
      generated_at: "2026-04-08T00:00:00Z",
      engine: "timescale-sql",
      warnings: [],
      rows: [
        {
          kind: "oat_bin",
          equipment_id: "SYN_CHW_1",
          oat_bin: "60-70",
          run_hours: 12.5,
        },
        {
          kind: "oat_bin",
          equipment_id: "SYN_CHW_1",
          oat_bin: "70-80",
          run_hours: 8,
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
      query_id: "mechanical-cooling",
    });
    expect(env.rows[0]?.bin_label).toBe("60-70");
    expect(env.rows[0]?.hours).toBe(12.5);
    const { figure, bins } = mechFigure(env.rows);
    expect(bins).toHaveLength(2);
    expect(figure?.data?.length).toBeGreaterThan(0);
    expect(figure?.meta?.provenance).toMatch(/mechanical-cooling/);
    expect(figure?.data?.[0]?.y).toEqual(expect.arrayContaining([12.5, 8]));
  });

  it("economizer tip rows drive delta scatter + temps overlay", () => {
    const tipRows = Array.from({ length: 6 }, (_, i) => ({
      ts: `2026-04-01T0${i}:00:00Z`,
      equipment_id: "SYN_AHU_E",
      oa_t: 50 + i,
      rat: 72,
      mat: 65 + i * 0.4,
      sat: 55,
      oa_damper_pct: 35 + i,
      delta_or_f: 50 + i - 72,
      delta_mr_f: 65 + i * 0.4 - 72,
      fan_on: true,
    }));
    const env = normalizeTipOverviewEnvelope("economizer", {
      schema_version: "analytics-envelope-v1",
      query_version: "economizer-diagnostics-v1",
      generated_at: "2026-04-08T00:00:00Z",
      engine: "timescale-sql",
      warnings: [],
      rows: tipRows,
      equipment: [],
      points: [],
      skipped: [],
      query_id: "economizer",
    });
    expect(env.points).toHaveLength(6);
    expect(env.points[0]?.identifiable).toBe(true);
    expect(env.points[0]?.fan_on).toBe(true);
    expect(env.points[0]?.oat_f).toBe(50);
    expect(env.points[0]?.damper_fb_pct).toBe(35);
    expect(env.points[0]?.mat_resid_f).toBeCloseTo(
      65 - (72 + (35 / 100) * (50 - 72)),
      6,
    );
    const scatter = econDeltaScatter(env.points, 10);
    expect(scatter).toBeTruthy();
    expect(scatter?.layout?.xaxis?.title).toMatch(/OAT − RAT/);
    expect(scatter?.layout?.yaxis?.title).toMatch(/MAT − RAT/);
    expect(
      scatter?.data?.some((t) => t.name === "SYN_AHU_E" && t.mode === "markers"),
    ).toBe(true);
    const temps = econTempsOverlay(env.points, null);
    expect(temps.figure?.layout?.title).toMatch(/Free-cooling temps/);
    expect(temps.figure?.data?.some((t) => t.name === "OAT")).toBe(true);
    expect(temps.figure?.data?.some((t) => t.name === "OA damper %")).toBe(
      true,
    );
  });

  it("bas-vs-web tip rows drive BAS/Web overlay traces", () => {
    const env = normalizeTipOverviewEnvelope("bas-vs-web-oat", {
      schema_version: "analytics-envelope-v1",
      query_version: "bas-vs-web-oat-v3",
      generated_at: "2026-04-08T00:00:00Z",
      engine: "timescale-sql",
      warnings: [],
      rows: [
        {
          ts: "2026-04-01T00:00:00Z",
          equipment_id: "SYN_WX",
          bas_oa_t: 70,
          web_oa_t: 68,
          delta_c: 2,
        },
        {
          ts: "2026-04-01T01:00:00Z",
          equipment_id: "SYN_WX",
          bas_oa_t: 71,
          web_oa_t: 69,
          delta_c: 2,
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
      query_id: "bas-vs-web-oat",
    });
    expect(env.points[0]?.bas_oat_c).toBe(70);
    expect(env.points[0]?.web_oat_c).toBe(68);
    const overlay = basOverlay(env.points, 5);
    expect(overlay?.data?.some((t) => t.name === "BAS oa_t")).toBe(true);
    expect(overlay?.data?.some((t) => t.name === "Web OAT")).toBe(true);
    expect(overlay?.meta?.provenance).toMatch(/bas-vs-web-oat/);
  });

  it("does not qualify off-fan, low-delta, or missing-MAT rows", () => {
    const env = normalizeTipOverviewEnvelope(
      "economizer",
      {
        schema_version: "analytics-envelope-v1",
        query_version: "economizer-diagnostics-v1",
        generated_at: "2026-04-08T00:00:00Z",
        engine: "timescale-sql",
        warnings: [],
        rows: [
          {
            ts: "2026-04-01T01:00:00Z",
            equipment_id: "SYN_AHU_E",
            oa_t: 50,
            rat: 72,
            mat: 60,
            delta_or_f: -22,
            delta_mr_f: -12,
            fan_on: false,
          },
          {
            ts: "2026-04-01T02:00:00Z",
            equipment_id: "SYN_AHU_E",
            oa_t: 70,
            rat: 72,
            mat: 71,
            delta_or_f: -2,
            delta_mr_f: -1,
            fan_on: true,
          },
          {
            ts: "2026-04-01T03:00:00Z",
            equipment_id: "SYN_AHU_E",
            oa_t: 50,
            rat: 72,
            delta_or_f: -22,
            fan_on: true,
          },
          {
            ts: "2026-04-01T04:00:00Z",
            equipment_id: "SYN_AHU_E",
            oa_t: 50,
            rat: 72,
            mat: 60,
            delta_or_f: -22,
            delta_mr_f: -12,
          },
        ],
        equipment: [],
        points: [],
        skipped: [],
        query_id: "economizer",
      },
      { dtMinF: 10 },
    );
    expect(env.points.every((p) => p.identifiable !== true)).toBe(true);
    expect(env.points.every((p) => p.fan_on !== true || p.identifiable !== true)).toBe(
      true,
    );
    expect(env.points.find((p) => p.timestamp_utc === "2026-04-01T04:00:00Z")?.fan_on).toBe(
      false,
    );
    expect(env.warnings[0]).toMatch(/not qualified/);
    expect(econDeltaScatter(env.points, 10)).toBeNull();
  });

  it("explains an empty economizer, runtime, mechanical-cooling, and BAS envelope", () => {
    const empty = {
      schema_version: "analytics-envelope-v1",
      query_version: "v",
      generated_at: "",
      engine: "timescale-sql",
      warnings: [],
      rows: [],
      equipment: [],
      points: [],
      skipped: [],
    };
    expect(normalizeTipOverviewEnvelope("economizer", empty).warnings[0]).toMatch(
      /Fan-on proof/,
    );
    expect(normalizeTipOverviewEnvelope("runtime", empty).warnings[0]).toMatch(
      /motor weekly/,
    );
    expect(
      normalizeTipOverviewEnvelope("mechanical-cooling", empty).warnings[0],
    ).toMatch(/outdoor-air bins/);
    expect(normalizeTipOverviewEnvelope("bas-vs-web-oat", empty).warnings[0]).toMatch(
      /BAS and web/,
    );
  });

  it("does not clobber legacy DataFusion points already present", () => {
    const env = normalizeTipOverviewEnvelope("economizer", {
      schema_version: "1",
      query_version: "economizer-diagnostics-v1",
      generated_at: "",
      engine: "datafusion",
      warnings: [],
      rows: [{ equipment_id: "AHU_1", n_identifiable: 1 }],
      equipment: [],
      points: [
        {
          equipment_id: "AHU_1",
          identifiable: true,
          delta_or_f: -5,
          delta_mr_f: -2,
          timestamp_utc: "2026-07-01T00:00:00Z",
        },
      ],
      skipped: [],
    });
    expect(env.points).toHaveLength(1);
    expect(env.points[0]?.delta_or_f).toBe(-5);
  });
});

describe("C4 FDD / RCx plot contracts vs tip API roles", () => {
  it("FDD ruleResultChart known answer keeps fault lane contract", () => {
    const fig = ruleResultChart(
      [
        {
          timestamp_utc: "2026-04-01T00:00:00Z",
          sat: 55,
          rat: 72,
          oa_damper_pct: 40,
        },
        {
          timestamp_utc: "2026-04-01T01:00:00Z",
          sat: 58,
          rat: 72,
          oa_damper_pct: 55,
        },
      ],
      {
        equipmentId: "SYN_AHU_FDD",
        ruleId: "FC1",
        roles: ["sat", "rat", "oa_damper_pct"],
        confirmedFault: [0, 1],
      },
    );
    expect(fig?.data.some((t) => t.name === chartContract.ruleResultChart.fault_trace)).toBe(
      true,
    );
    expect(fig?.layout?.xaxis?.title).toBe(
      chartContract.ruleResultChart.xaxis_title,
    );
  });

  it("Overview PNG stems remain locked for tip Overview/RCx downloads", () => {
    const stems = new Set(chartContract.overview_png_stems);
    for (const stem of Object.values(
      chartContract.png_stem_vocabulary.react_overview_rcx,
    )) {
      expect(stems.has(stem)).toBe(true);
    }
    expect(stems.has("bas_vs_web_oat")).toBe(true);
    expect(stems.has("mech_cooling_oat_bins")).toBe(true);
    expect(stems.has("economizer_free_cooling_delta")).toBe(true);
  });
});
