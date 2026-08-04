import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { PlotlyHost, sanitizePlotlyFigure } from "./PlotlyHost";

describe("sanitizePlotlyFigure", () => {
  it("strips template and rejects empty data", () => {
    const clean = sanitizePlotlyFigure({
      data: [{ x: [1], y: [2], type: "bar", name: "a" }],
      layout: { title: "T", template: { data: {}, layout: {} } },
    });
    expect(clean?.layout?.template).toBeUndefined();
    expect(clean?.data).toHaveLength(1);
    expect(sanitizePlotlyFigure(null)).toBeNull();
    expect(sanitizePlotlyFigure({ data: [], layout: {} })).toBeNull();
  });
});

describe("PlotlyHost", () => {
  const newPlot = vi.fn(async () => undefined);
  const react = vi.fn(async () => undefined);
  const purge = vi.fn();

  beforeEach(() => {
    newPlot.mockClear();
    react.mockClear();
    purge.mockClear();
    window.Plotly = {
      newPlot,
      react,
      purge,
      Plots: { resize: vi.fn() },
    };
  });

  afterEach(() => {
    delete window.Plotly;
  });

  it("keeps host mounted while loading and draws when figure arrives", async () => {
    const figure = {
      data: [{ x: ["2026-01-01"], y: [10], type: "bar", name: "AHU" }],
      layout: { title: "Air", template: { data: {} } },
    };
    const { rerender, getByTestId, queryByTestId } = render(
      <PlotlyHost
        id="motor"
        label="Motor"
        figure={null}
        loading
        height={300}
        testId="overview-motor-air-plot"
      />,
    );
    expect(getByTestId("plotly-div-motor")).toBeTruthy();
    expect(queryByTestId("plotly-status-motor")?.textContent).toMatch(
      /Loading chart/,
    );

    rerender(
      <PlotlyHost
        id="motor"
        label="Motor"
        figure={figure}
        loading={false}
        height={300}
        testId="overview-motor-air-plot"
      />,
    );

    await waitFor(() => {
      expect(react.mock.calls.length + newPlot.mock.calls.length).toBeGreaterThan(
        0,
      );
    });
    const call = (react.mock.calls[0] ?? newPlot.mock.calls[0]) as unknown[];
    expect(call[1]).toEqual(figure.data);
    expect((call[2] as { template?: unknown }).template).toBeUndefined();
    await waitFor(() => {
      expect(getByTestId("plotly-meta-motor").textContent).toMatch(/rendered/);
    });
  });
});
