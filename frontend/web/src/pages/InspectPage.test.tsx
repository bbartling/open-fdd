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
});
