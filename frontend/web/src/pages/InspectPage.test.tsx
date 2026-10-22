import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { InspectPage } from "../pages/InspectPage";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async () => ({ version: "3.3.1+abc1234" })),
}));

vi.mock("../api/mappingApi", () => ({
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    equipment: [
      { equipment_id: "AHU_1" },
      { equipment_id: "BOILER_1" },
    ],
  })),
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: { params: {} } })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

vi.mock("../api/analyticsApi", () => ({
  postInspect: vi.fn(async ({ equipment_ids }: { equipment_ids: string[] }) => ({
    coverage: {
      plottable_columns: ["sat", "duct_static"],
      columns_plotted: ["sat", "duct_static"],
      first_timestamp: "2026-03-16T00:40:00",
      last_timestamp: "2026-03-16T00:45:00",
    },
    points: [
      {
        timestamp_utc: "2026-03-16T00:40:00",
        equipment_id: equipment_ids[0],
        sat: 55,
        duct_static: 0.8,
      },
      {
        timestamp_utc: "2026-03-16T00:45:00",
        equipment_id: equipment_ids[0],
        sat: 56,
        duct_static: 0.9,
      },
    ],
    warnings: [],
  })),
}));

vi.mock("../components/widgets/PlotlyHost", () => ({
  PlotlyHost: ({ testId }: { testId?: string }) => (
    <div data-testid={testId ?? "plotly"} />
  ),
}));

import { postInspect } from "../api/analyticsApi";

describe("InspectPage", () => {
  beforeEach(() => {
    vi.mocked(postInspect).mockClear();
  });

  it("renders equipment select and inspect plot", async () => {
    render(
      <MemoryRouter initialEntries={["/inspect?site=B1&eq=AHU_1"]}>
        <InspectPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("inspect-page")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("overview-inspect-eq")).toBeTruthy();
    });
    await waitFor(() => {
      expect(postInspect).toHaveBeenCalled();
    });
    expect(screen.getByTestId("overview-inspect-plot")).toBeTruthy();
    const select = screen.getByTestId("overview-inspect-eq").querySelector("select");
    fireEvent.change(select!, { target: { value: "BOILER_1" } });
    await waitFor(() => {
      const last = vi.mocked(postInspect).mock.calls.at(-1)?.[0] as {
        equipment_ids: string[];
      };
      expect(last.equipment_ids).toEqual(["BOILER_1"]);
    });
  });

  it("downloads JSON for every selected series with names and units", async () => {
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    let blob: Blob | null = null;
    URL.createObjectURL = vi.fn((value: Blob) => {
      blob = value;
      return "blob:inspect";
    }) as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
    const anchors: HTMLAnchorElement[] = [];
    const orig = document.createElement.bind(document);
    const spy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = orig(tag);
      if (tag.toLowerCase() === "a") anchors.push(element as HTMLAnchorElement);
      return element;
    });
    try {
      render(
        <MemoryRouter initialEntries={["/inspect?site=B1&eq=AHU_1"]}>
          <InspectPage />
        </MemoryRouter>,
      );
      await waitFor(() => {
        const button = screen.getByTestId("overview-dl-inspect").querySelector("button");
        expect(button?.disabled).toBe(false);
      });
      const label = screen.getByTestId("overview-dl-inspect").textContent ?? "";
      expect(label).toMatch(/JSON/i);
      anchors.length = 0;
      fireEvent.click(screen.getByTestId("overview-dl-inspect").querySelector("button")!);
      const anchor = anchors.at(-1) ?? null;
      expect(blob).toBeInstanceOf(Blob);
      expect(blob?.type).toBe("application/json");
      expect(anchor).not.toBeNull();
      expect(anchor?.download).toBe("AHU_1_inspect.json");
      expect(anchor?.download.endsWith(".csv")).toBe(false);
      const raw = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result ?? ""));
        reader.onerror = () => reject(reader.error ?? new Error("blob read failed"));
        reader.readAsText(blob!);
      });
      const doc = JSON.parse(raw) as {
        format: string;
        equipment_id: string;
        source: string;
        window: { first: string | null; last: string | null };
        series: Array<{ name: string; unit: string | null; points: unknown[] }>;
      };
      expect(doc.format).toBe("openfdd.inspect-sample.v1");
      expect(doc.equipment_id).toBe("AHU_1");
      expect(doc.source).toBe("POST /api/analytics/inspect");
      expect(doc.window).toEqual({
        first: "2026-03-16T00:40:00",
        last: "2026-03-16T00:45:00",
      });
      expect(doc.series.map((series) => [series.name, series.unit, series.points.length])).toEqual([
        ["sat", "°F", 2],
        ["duct_static", "in. w.c.", 2],
      ]);
    } finally {
      spy.mockRestore();
      URL.createObjectURL = origCreate;
      URL.revokeObjectURL = origRevoke;
    }
  });
});
