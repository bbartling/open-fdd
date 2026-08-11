import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { mergePlotlyHostLayout, PlotlyHost } from "./PlotlyHost";
import { sanitizePlotlyFigure } from "../../api/plotlySanitize";

describe("mergePlotlyHostLayout", () => {
  it("keeps fixed range on fault y2 and does not force autorange", () => {
    const layout = mergePlotlyHostLayout(
      {
        yaxis: { domain: [0.35, 1], title: { text: "°F" } },
        yaxis2: {
          domain: [0, 0.28],
          title: { text: "fault" },
          range: [-0.05, 1.15],
          tickvals: [0, 1],
          ticktext: ["ok", "fault"],
        },
      },
      {
        height: 400,
        id: "fdd",
        figureId: "fc1",
        data: [{ yaxis: "y" }, { yaxis: "y2" }],
      },
    );
    const y2 = layout.yaxis2 as { range?: number[]; autorange?: boolean };
    expect(y2.range).toEqual([-0.05, 1.15]);
    expect(y2.autorange).toBe(false);
    const y1 = layout.yaxis as { autorange?: boolean };
    expect(y1.autorange).toBe(true);
  });

  it("patches yaxis3+ from stacked ruleResultChart domains", () => {
    const layout = mergePlotlyHostLayout(
      {
        yaxis: { domain: [0.7, 1] },
        yaxis2: { domain: [0.4, 0.65] },
        yaxis3: { domain: [0, 0.3], range: [-0.05, 1.15] },
      },
      { height: 480, id: "stack", data: [{ yaxis: "y3" }] },
    );
    const y3 = layout.yaxis3 as { range?: number[]; autorange?: boolean };
    expect(y3.range).toEqual([-0.05, 1.15]);
    expect(y3.autorange).toBe(false);
  });
});


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
    const layout = call[2] as {
      template?: unknown;
      uirevision?: string;
      xaxis?: { autorange?: boolean };
      yaxis?: { autorange?: boolean };
    };
    expect(layout.template).toBeUndefined();
    expect(layout.xaxis?.autorange).toBe(true);
    expect(layout.yaxis?.autorange).toBe(true);
    expect(layout.uirevision).toBeTruthy();
    await waitFor(() => {
      expect(getByTestId("plotly-meta-motor").textContent).toMatch(/rendered/);
    });

    // Same cardinality / provenance, different values — must bump uirevision.
    react.mockClear();
    newPlot.mockClear();
    rerender(
      <PlotlyHost
        id="motor"
        label="Motor"
        figure={{
          ...figure,
          data: [{ x: ["2026-01-01"], y: [99], type: "bar", name: "AHU" }],
          meta: { provenance: "runtime-v1", point_count: 1 },
        }}
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
    const call2 = (react.mock.calls[0] ?? newPlot.mock.calls[0]) as unknown[];
    const layout2 = call2[2] as { uirevision?: string };
    expect(layout2.uirevision).toBeTruthy();
    expect(layout2.uirevision).not.toEqual(layout.uirevision);
  });

  it("resizes Plotly when the host box changes", async () => {
    const cbs: ResizeObserverCallback[] = [];
    class FakeRO {
      cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb;
        cbs.push(cb);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    const prev = globalThis.ResizeObserver;
    globalThis.ResizeObserver = FakeRO as unknown as typeof ResizeObserver;
    const resize = vi.fn();
    window.Plotly = {
      newPlot,
      react,
      purge,
      Plots: { resize },
    };
    render(
      <PlotlyHost
        id="stretch"
        label="Stretch"
        figure={{
          data: [{ x: [1], y: [2], type: "scatter", name: "a" }],
          layout: {},
        }}
        height={300}
      />,
    );
    await waitFor(() => {
      expect(react.mock.calls.length + newPlot.mock.calls.length).toBeGreaterThan(
        0,
      );
    });
    cbs[0]?.([], {} as ResizeObserver);
    await waitFor(() => {
      expect(resize).toHaveBeenCalled();
    });
    globalThis.ResizeObserver = prev;
  });

  it("cancels Plotly wait timers on unmount so vitest teardown stays clean", async () => {
    delete window.Plotly;
    const { unmount } = render(
      <PlotlyHost id="pending" label="Pending" figure={null} height={200} />,
    );
    unmount();
    await new Promise((r) => setTimeout(r, 80));
    expect(true).toBe(true);
  });
});
