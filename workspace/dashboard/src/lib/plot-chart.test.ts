import { describe, expect, it } from "vitest";
import { buildPlotTraces, faultBoolY, parsePlotAxisLimit } from "./plot-chart";

describe("plot-chart", () => {
  it("faultBoolY maps flags to 0/1", () => {
    expect(faultBoolY([0, 1, 0])).toEqual([0, 1, 0]);
  });

  it("builds temp on y and humidity on y2", () => {
    const { traces, layout } = buildPlotTraces(
      {
        timestamps: ["t1", "t2"],
        series: { "oa-t": [70, 71], "oa-h": [40, 41] },
        series_kinds: { "oa-t": "temperature", "oa-h": "humidity" },
        fault_plots: {},
        fault_panels: [],
      },
      { enabledFaults: new Set(), showBounds: false, theme: "dark" },
    );
    expect(traces).toHaveLength(2);
    expect(traces[0].yaxis).toBe("y");
    expect(traces[1].yaxis).toBe("y2");
    expect(layout.yaxis2).toBeDefined();
  });

  it("adds fault lane on y2 when only temperature series", () => {
    const { traces, layout } = buildPlotTraces(
      {
        timestamps: ["t1", "t2", "t3"],
        series: { "oa-t": [70, 71, 72] },
        series_kinds: { "oa-t": "temperature" },
        fault_plots: { "rule-a": [0, 1, 1] },
        fault_panels: [{ key: "rule-a", title: "Flatline", color: "#f00" }],
        fault_totals: { "rule-a": 2 },
      },
      { enabledFaults: new Set(["rule-a"]), showBounds: false, theme: "dark" },
    );
    expect(traces).toHaveLength(2);
    expect(traces[1].yaxis).toBe("y2");
    expect(layout.yaxis2).toMatchObject({ range: [-0.08, 1.08], title: "Faults (0/1)", automargin: true });
  });

  it("adds fault lane on y3 when humidity and faults both present", () => {
    const { traces, layout } = buildPlotTraces(
      {
        timestamps: ["t1", "t2"],
        series: { "oa-t": [70, 71], "oa-h": [40, 41] },
        series_kinds: { "oa-t": "temperature", "oa-h": "humidity" },
        fault_plots: { "rule-a": [0, 1] },
        fault_panels: [{ key: "rule-a", title: "Flatline", color: "#f00" }],
        fault_totals: { "rule-a": 1 },
      },
      { enabledFaults: new Set(["rule-a"]), showBounds: false, theme: "dark" },
    );
    expect(traces).toHaveLength(3);
    expect(traces[2].yaxis).toBe("y3");
    expect(layout.yaxis3).toMatchObject({ range: [-0.08, 1.08], title: "Faults (0/1)", automargin: true });
  });

  it("applies manual left and right axis ranges", () => {
    const { layout } = buildPlotTraces(
      {
        timestamps: ["t1", "t2"],
        series: { "oa-t": [70, 71], "oa-h": [40, 41] },
        series_kinds: { "oa-t": "temperature", "oa-h": "humidity" },
        fault_plots: {},
        fault_panels: [],
      },
      {
        enabledFaults: new Set(),
        showBounds: false,
        theme: "dark",
        yLeftLimit: { min: 65, max: 80 },
        yRightLimit: { min: 30, max: 55 },
      },
    );
    expect(layout.yaxis).toMatchObject({ range: [65, 80], autorange: false });
    expect(layout.yaxis2).toMatchObject({ range: [30, 55], autorange: false });
  });

  it("parsePlotAxisLimit rejects invalid ranges", () => {
    expect(parsePlotAxisLimit("", "")).toBeNull();
    expect(parsePlotAxisLimit("70", "60")).toBeNull();
    expect(parsePlotAxisLimit("65", "80")).toEqual({ min: 65, max: 80 });
  });
});
