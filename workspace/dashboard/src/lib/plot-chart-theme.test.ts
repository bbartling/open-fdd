import { describe, expect, it } from "vitest";
import { getPlotlyThemeLayout } from "./plotly-theme";
import { buildPlotTraces } from "./plot-chart";

describe("plot-chart theme integration", () => {
  it("switching theme updates chart layout colors", () => {
    const data = {
      timestamps: ["2026-01-01T00:00:00", "2026-01-01T01:00:00"],
      series: { "oa-t": [70, 71] },
      series_kinds: { "oa-t": "temperature" },
      fault_plots: {},
      fault_panels: [],
    };
    const light = buildPlotTraces(data, {
      enabledFaults: new Set(),
      showBounds: false,
      theme: "light",
    });
    const dark = buildPlotTraces(data, {
      enabledFaults: new Set(),
      showBounds: false,
      theme: "dark",
    });
    expect(light.layout.plot_bgcolor).toBe(getPlotlyThemeLayout("light").plot_bgcolor);
    expect(dark.layout.plot_bgcolor).toBe(getPlotlyThemeLayout("dark").plot_bgcolor);
    expect(light.layout.plot_bgcolor).not.toBe(dark.layout.plot_bgcolor);
  });
});
