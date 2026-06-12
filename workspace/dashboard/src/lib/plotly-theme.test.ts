import { describe, expect, it } from "vitest";
import { getPlotlyThemeLayout } from "./plotly-theme";

describe("plotly-theme", () => {
  it("light mode uses light plot background and dark text", () => {
    const layout = getPlotlyThemeLayout("light");
    expect(layout.plot_bgcolor).toBe("#ffffff");
    expect(layout.font.color).toBe("#1a2332");
  });

  it("dark mode uses dark plot background and light text", () => {
    const layout = getPlotlyThemeLayout("dark");
    expect(layout.plot_bgcolor).toBe("#161b24");
    expect(layout.font.color).toBe("#e6edf3");
  });

  it("axis grid colors differ by theme", () => {
    const light = getPlotlyThemeLayout("light");
    const dark = getPlotlyThemeLayout("dark");
    expect(light.xaxis.gridcolor).not.toBe(dark.xaxis.gridcolor);
  });
});
