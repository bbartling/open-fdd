import { describe, expect, it } from "vitest";
import { downsample, ruleResultChart, vavComfortDonut } from "./charts";
import { REQUIRED_CHART_APIS, VIBE19_SECTIONS } from "./contract";

describe("vibe19 contract", () => {
  it("keeps frozen main sections", () => {
    expect(VIBE19_SECTIONS).toContain("Overview");
    expect(VIBE19_SECTIONS).toContain("Run Rules");
    expect(VIBE19_SECTIONS).toContain("FDD Plots");
  });

  it("lists required chart APIs", () => {
    expect(REQUIRED_CHART_APIS).toContain("rule_result_chart");
    expect(REQUIRED_CHART_APIS.length).toBeGreaterThanOrEqual(10);
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
      series: [{ name: "sat", points: [{ t: 0, y: 55 }, { t: 1, y: 56 }] }],
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
});
