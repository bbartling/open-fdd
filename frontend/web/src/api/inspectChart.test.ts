import { describe, expect, it } from "vitest";
import chartContract from "./charts.contract.json";
import { equipmentInspectionChart } from "./inspectChart";
import {
  overviewRcxCompanionPngStem,
  overviewRcxPngStem,
} from "./rcxOverviewPresets";

describe("inspectChart", () => {
  it("stacks domain axes with Inspection title from contract", () => {
    const fig = equipmentInspectionChart(
      [
        { timestamp_utc: "2026-01-01T00:00:00Z", sat: 55, fan_status: 1 },
        { timestamp_utc: "2026-01-01T01:00:00Z", sat: 56, fan_status: 0 },
      ],
      { equipmentId: "AHU_1", columns: ["sat", "fan_status"] },
    );
    expect(fig).not.toBeNull();
    const expected = chartContract.inspectChart.title_template.replace(
      "{equipment_id}",
      "AHU_1",
    );
    expect(fig?.layout?.title).toBe(expected);
    expect((fig?.layout?.yaxis as { title?: string })?.title).toBe("sat");
    expect((fig?.layout?.yaxis2 as { title?: string })?.title).toBe(
      "fan_status",
    );
    expect((fig?.layout?.yaxis as { domain?: number[] })?.domain?.[0]).toBeGreaterThan(
      (fig?.layout?.yaxis2 as { domain?: number[] })?.domain?.[0] ?? 1,
    );
    expect(fig?.data.every((t) => t.line?.shape === "linear")).toBe(true);
    expect(fig?.data.every((t) => t.line?.width === 1.4)).toBe(true);
  });
});

describe("overview RCx PNG stems", () => {
  it("maps Overview presets to contract stems", () => {
    expect(overviewRcxPngStem("mech_cooling_oat_bins")).toBe(
      "mech_cooling_oat_bins",
    );
    expect(overviewRcxPngStem("economizer_delta")).toBe(
      "economizer_free_cooling_delta",
    );
    expect(overviewRcxCompanionPngStem("bas_vs_web_oat")).toBe(
      "bas_web_oat_deviation_hist",
    );
    expect(overviewRcxCompanionPngStem("ahu_motor_weekly")).toBeNull();
    const stems = new Set(chartContract.overview_png_stems);
    for (const stem of Object.values(
      chartContract.png_stem_vocabulary.react_overview_rcx,
    )) {
      expect(stems.has(stem)).toBe(true);
    }
  });
});
