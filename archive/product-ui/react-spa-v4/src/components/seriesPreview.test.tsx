import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PlotlyFigure } from "../api/plotDataset";
import { SeriesPreview } from "./SeriesPreview";
import { recentSeriesPreview } from "./seriesPreview";

function seriesFigure(
  xs: string[],
  traces: Array<{ name: string; y: Array<number | null> }>,
): PlotlyFigure {
  return {
    data: traces.map((t) => ({
      type: "scatter",
      mode: "lines",
      name: t.name,
      x: xs,
      y: t.y,
    })),
  };
}

describe("recentSeriesPreview", () => {
  it("returns the newest rows first from the loaded window", () => {
    const xs = ["2024-01-01T00:00:00Z", "2024-01-01T00:05:00Z", "2024-01-01T00:10:00Z"];
    const table = recentSeriesPreview(
      seriesFigure(xs, [
        { name: "zone_t", y: [70, 71, 72] },
        { name: "confirmed_fault", y: [0, 0, 1] },
      ]),
      10,
    );
    expect(table?.rows.map((r) => r.timestamp)).toEqual([
      "2024-01-01T00:10:00Z",
      "2024-01-01T00:05:00Z",
      "2024-01-01T00:00:00Z",
    ]);
    expect(table?.rows[0]).toMatchObject({ zone_t: "72", confirmed_fault: "1" });
    expect(table?.columns).toEqual(["timestamp", "zone_t", "confirmed_fault"]);
  });

  it("joins traces that do not share an index", () => {
    const fig: PlotlyFigure = {
      data: [
        {
          type: "scatter",
          name: "AHU_1",
          x: ["2024-03-01T00:00:00Z", "2024-03-01T01:00:00Z"],
          y: [55, 56],
        },
        {
          type: "scatter",
          name: "AHU_2",
          x: ["2024-03-01T01:00:00Z", "2024-03-01T02:00:00Z"],
          y: [60, 61],
        },
      ],
    };
    const table = recentSeriesPreview(fig, 10);
    expect(table?.rows.map((r) => r.timestamp)).toEqual([
      "2024-03-01T02:00:00Z",
      "2024-03-01T01:00:00Z",
      "2024-03-01T00:00:00Z",
    ]);
    expect(table?.rows[0]).toMatchObject({ AHU_1: "", AHU_2: "61" });
    expect(table?.rows[1]).toMatchObject({ AHU_1: "56", AHU_2: "60" });
  });

  it("skips charts that are not a time series", () => {
    const bars: PlotlyFigure = {
      data: [{ type: "bar", name: "fail", x: ["VAV_1", "VAV_2"], y: [4, 8] }],
    };
    const scatter: PlotlyFigure = {
      data: [{ type: "scatter", name: "kWh", x: [10, 20, 30], y: [1, 2, 3] }],
    };
    expect(recentSeriesPreview(bars, 10)).toBeNull();
    expect(recentSeriesPreview(scatter, 10)).toBeNull();
    expect(recentSeriesPreview(null, 10)).toBeNull();
  });

  it("does not keep rows older than the requested tail", () => {
    const xs = Array.from({ length: 30 }, (_, i) => `2024-04-01T00:${String(i).padStart(2, "0")}:00Z`);
    const table = recentSeriesPreview(
      seriesFigure(xs, [{ name: "sat", y: xs.map((_, i) => i) }]),
      10,
    );
    expect(table?.rows).toHaveLength(10);
    expect(table?.rows[0].timestamp).toBe("2024-04-01T00:29:00Z");
    expect(table?.rows[9].timestamp).toBe("2024-04-01T00:20:00Z");
    expect(table?.rows.some((r) => r.timestamp === "2024-04-01T00:00:00Z")).toBe(false);
  });
});

describe("SeriesPreview", () => {
  const figure = seriesFigure(
    Array.from({ length: 15 }, (_, i) => `2024-05-01T00:${String(i).padStart(2, "0")}:00Z`),
    [{ name: "zone_t", y: Array.from({ length: 15 }, (_, i) => 60 + i) }],
  );

  it("defaults to 10 newest rows and follows this card's dropdown", () => {
    render(<SeriesPreview id="plots-preview" figure={figure} testId="plots-preview" />);
    const select = screen.getByTestId("plots-preview-rows").querySelector("select");
    expect(select?.value).toBe("10");
    expect(
      [...(select?.options ?? [])].map((o) => o.value),
    ).toEqual(["10", "20", "50", "100", "500"]);
    const table = screen.getByTestId("plots-preview-table");
    expect(table.querySelector("tbody td")?.textContent).toBe("2024-05-01T00:14:00Z");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(10);
    expect(screen.getByText("Series preview (most recent 10)")).toBeTruthy();
    expect(screen.queryByText(/first rows/i)).toBeNull();

    fireEvent.change(select!, { target: { value: "20" } });
    expect(table.querySelectorAll("tbody tr")).toHaveLength(15);
    expect(table.querySelector("tbody td")?.textContent).toBe("2024-05-01T00:14:00Z");
    expect(screen.getByText("Series preview (most recent 20)")).toBeTruthy();
  });

  it("keeps a separate row count on each plot card", () => {
    render(
      <>
        <SeriesPreview id="rcx-plot-preview" figure={figure} testId="rcx-plot-preview" />
        <SeriesPreview
          id="rcx-companion-preview"
          figure={figure}
          testId="rcx-companion-preview"
        />
      </>,
    );
    const main = screen.getByTestId("rcx-plot-preview-rows").querySelector("select")!;
    const companion = screen
      .getByTestId("rcx-companion-preview-rows")
      .querySelector("select")!;
    fireEvent.change(main, { target: { value: "50" } });
    expect(main.value).toBe("50");
    expect(companion.value).toBe("10");
    expect(
      screen.getByTestId("rcx-plot-preview-table").querySelectorAll("tbody tr"),
    ).toHaveLength(15);
    expect(
      screen.getByTestId("rcx-companion-preview-table").querySelectorAll("tbody tr"),
    ).toHaveLength(10);
  });
});
