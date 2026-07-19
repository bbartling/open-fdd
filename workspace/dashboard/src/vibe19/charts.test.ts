import { describe, expect, it } from "vitest";
import {
  basVsWebOatOverlay,
  downsample,
  meteringBarScatter,
  motorWeeklyRuntimeChart,
  multiEquipmentBox,
  oatScatter,
  ruleResultChart,
  sensorFaultChart,
  vavComfortDonut,
} from "./charts";
import {
  RCX_PRESETS,
  REQUIRED_CHART_APIS,
  REQUIRED_RCX_PRESET_IDS,
  VIBE19_SECTIONS,
} from "./contract";

describe("vibe19 contract", () => {
  it("keeps the frozen eight sections and excludes Energy Model", () => {
    expect([...VIBE19_SECTIONS]).toEqual([
      "Overview",
      "Data Model",
      "Run Rules",
      "Results by Category",
      "FDD Plots",
      "RCx Plots",
      "Metering",
      "Export",
    ]);
    expect(VIBE19_SECTIONS).not.toContain("Energy Model");
  });

  it("lists required chart APIs", () => {
    expect(REQUIRED_CHART_APIS).toContain("rule_result_chart");
    expect(REQUIRED_CHART_APIS).toContain("multi_equipment_box");
    expect(REQUIRED_CHART_APIS).toContain("sensor_fault_chart");
    expect(REQUIRED_CHART_APIS.length).toBeGreaterThanOrEqual(10);
  });

  it("freezes RCx presets with weather policy", () => {
    expect(REQUIRED_RCX_PRESET_IDS.length).toBeGreaterThanOrEqual(12);
    const ids = new Set(RCX_PRESETS.map((p) => p.id));
    for (const id of REQUIRED_RCX_PRESET_IDS) {
      expect(ids.has(id)).toBe(true);
    }
    const cw = RCX_PRESETS.find((p) => p.id === "cw_reset_scatter");
    expect(cw?.weatherAxis).toBe("wet_bulb");
    const hw = RCX_PRESETS.find((p) => p.id === "hw_reset_scatter");
    expect(hw?.weatherAxis).toBe("dry_bulb");
  });
});

describe("vibe19 charts", () => {
  it("downsamples for display only", () => {
    const xs = Array.from({ length: 10000 }, (_, i) => i);
    expect(downsample(xs, 5000).length).toBeLessThanOrEqual(5000);
  });

  it("builds rule_result_chart with fault lane", () => {
    const fig = ruleResultChart({
      title: "t",
      series: [
        {
          name: "sat",
          points: [
            { t: 0, y: 55 },
            { t: 1, y: 56 },
          ],
        },
      ],
      confirmed: [
        { t: 0, fault: false },
        { t: 1, fault: true },
      ],
    });
    expect(fig.data.length).toBe(2);
    expect(fig.data[1].name).toBe("confirmed_fault");
  });

  it("builds comfort donut", () => {
    const fig = vavComfortDonut({ title: "c", inComfort: 9, outComfort: 1 });
    expect(fig.data[0].type).toBe("pie");
  });

  it("builds box / scatter / runtime / overlay / sensor / metering", () => {
    expect(multiEquipmentBox({ title: "b", series: [{ name: "a", values: [1, 2, 3] }] }).data[0].type).toBe(
      "box",
    );
    expect(oatScatter({ title: "s", x: [1, 2], y: [3, 4] }).data[0].mode).toBe("markers");
    expect(
      motorWeeklyRuntimeChart({ title: "m", weeks: ["W1"], hours: [10] }).data[0].type,
    ).toBe("bar");
    expect(
      basVsWebOatOverlay({
        title: "o",
        bas: [{ t: 0, y: 70 }],
        web: [{ t: 0, y: 68 }],
      }).data.length,
    ).toBe(2);
    expect(
      sensorFaultChart({
        title: "sf",
        sensors: ["sat"],
        days: ["d1"],
        z: [[0.2]],
      }).data[0].type,
    ).toBe("heatmap");
    expect(
      meteringBarScatter({
        title: "met",
        months: ["Jan"],
        usage: [100],
        degreeDays: [200],
      }).data.length,
    ).toBe(2);
  });
});
