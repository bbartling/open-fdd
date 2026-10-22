import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
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
      plottable_columns: ["sat", "mat"],
      columns_plotted: ["sat", "mat"],
      first_timestamp: "2026-03-16T00:40:00",
      last_timestamp: "2026-03-22T23:15:00",
    },
    points: [
      {
        timestamp_utc: "2026-03-16T00:40:00",
        equipment_id: equipment_ids[0],
        sat: 55,
        mat: 60,
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
import { getPackageMapping, listPackageBuildings } from "../api/mappingApi";

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="loc">{location.search}</span>;
}

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

  it("requests the historian once per equipment selection", async () => {
    vi.mocked(postInspect).mockImplementation(async () => ({
      coverage: {
        plottable_columns: ["sat", "mat", "rat"],
        columns_plotted: ["sat"],
        first_timestamp: "2026-03-16T00:40:00",
        last_timestamp: "2026-03-22T23:15:00",
      },
      points: [
        {
          timestamp_utc: "2026-03-16T00:40:00",
          equipment_id: "AHU_1",
          sat: 55,
        },
      ],
      warnings: [],
    }));
    render(
      <MemoryRouter initialEntries={["/inspect?site=B1&eq=AHU_1"]}>
        <InspectPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(vi.mocked(postInspect).mock.calls.length).toBe(1);
    });
    const select = screen.getByTestId("overview-inspect-eq").querySelector("select");
    fireEvent.change(select!, { target: { value: "BOILER_1" } });
    await waitFor(() => {
      expect(vi.mocked(postInspect).mock.calls.length).toBe(2);
    });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(vi.mocked(postInspect).mock.calls.length).toBe(2);
    const buildings = vi.mocked(postInspect).mock.calls.map(
      (call) => (call[0] as { building_id: string }).building_id,
    );
    expect(buildings).toEqual(["B1", "B1"]);
  });

  it("commits only the latest site when a previous inspect response arrives late", async () => {
    const maps = new Map<string, ReturnType<typeof deferred<{
      ok: boolean;
      equipment: Array<{ equipment_id: string }>;
    }>>>();
    const plots = new Map<string, ReturnType<typeof deferred<{
      coverage: Record<string, unknown>;
      points: Array<Record<string, unknown>>;
      warnings: string[];
    }>>>();
    vi.mocked(listPackageBuildings).mockResolvedValue(["SITE_A", "SITE_B"]);
    vi.mocked(getPackageMapping).mockImplementation(async (site: string) => {
      const slot = deferred<{
        ok: boolean;
        equipment: Array<{ equipment_id: string }>;
      }>();
      maps.set(site, slot);
      return slot.promise;
    });
    vi.mocked(postInspect).mockImplementation(async (body: { building_id?: string }) => {
      const site = String(body.building_id ?? "");
      const slot = deferred<{
        coverage: Record<string, unknown>;
        points: Array<Record<string, unknown>>;
        warnings: string[];
      }>();
      plots.set(site, slot);
      return slot.promise;
    });

    render(
      <MemoryRouter initialEntries={["/inspect?site=SITE_A&eq=EQ_A"]}>
        <LocationProbe />
        <InspectPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(maps.has("SITE_A")).toBe(true);
    });
    maps.get("SITE_A")!.resolve({
      ok: true,
      equipment: [{ equipment_id: "EQ_A" }],
    });
    await waitFor(() => {
      expect(plots.has("SITE_A")).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByTestId("sidebar-active-site")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("sidebar-active-site"), {
      target: { value: "SITE_B" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("loc").textContent).toContain("site=SITE_B");
    });
    expect(screen.getByTestId("loc").textContent ?? "").not.toContain("eq=EQ_A");
    await waitFor(() => {
      expect(maps.has("SITE_B")).toBe(true);
    });
    maps.get("SITE_B")!.resolve({
      ok: true,
      equipment: [{ equipment_id: "EQ_B" }],
    });
    await waitFor(() => {
      expect(plots.has("SITE_B")).toBe(true);
    });
    const siteBRequest = vi.mocked(postInspect).mock.calls.find(
      (call) => (call[0] as { building_id?: string }).building_id === "SITE_B",
    )?.[0] as { equipment_ids?: string[] } | undefined;
    expect(siteBRequest?.equipment_ids).toEqual(["EQ_B"]);
    expect(
      vi.mocked(postInspect).mock.calls.some(
        (call) =>
          (call[0] as { building_id?: string }).building_id === "SITE_B" &&
          (call[0] as { equipment_ids?: string[] }).equipment_ids?.[0] === "EQ_A",
      ),
    ).toBe(false);

    plots.get("SITE_B")!.resolve({
      coverage: {
        plottable_columns: ["sat"],
        columns_plotted: ["sat"],
        first_timestamp: "SITE_B_MARKER",
        last_timestamp: "SITE_B_END",
      },
      points: [{ timestamp_utc: "SITE_B_MARKER", equipment_id: "EQ_B", sat: 1 }],
      warnings: [],
    });
    await waitFor(() => {
      expect(screen.getByTestId("overview-inspect-meta").textContent).toContain(
        "SITE_B_MARKER",
      );
    });
    plots.get("SITE_A")!.resolve({
      coverage: {
        plottable_columns: ["sat"],
        columns_plotted: ["sat"],
        first_timestamp: "SITE_A_MARKER",
        last_timestamp: "SITE_A_END",
      },
      points: [{ timestamp_utc: "SITE_A_MARKER", equipment_id: "EQ_A", sat: 9 }],
      warnings: [],
    });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getByTestId("overview-inspect-meta").textContent).toContain(
      "SITE_B_MARKER",
    );
    expect(screen.getByTestId("overview-inspect-meta").textContent).not.toContain(
      "SITE_A_MARKER",
    );
    const select = screen.getByTestId("overview-inspect-eq").querySelector("select");
    expect(select?.value).toBe("EQ_B");
  });
});
