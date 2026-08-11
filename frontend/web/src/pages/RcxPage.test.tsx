import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { RcxPage } from "./RcxPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    equipment: [
      {
        equipment_id: "AHU_1",
        roles: { sat: "sat" },
        columns: [{ column: "sat", role: "sat" }],
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: {} })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/analyticsApi", () => ({
  listRcxPresets: vi.fn(async () => [
    {
      id: "ahu_sat",
      title: "AHU SAT",
      family: "AHU",
      chart: "timeseries",
      role_col: "sat",
    },
    {
      id: "ahu_rat",
      title: "AHU RAT",
      family: "AHU",
      chart: "timeseries",
      role_col: "rat",
    },
  ]),
  postRcxPreset: vi.fn(async () => ({
    engine: "datafusion",
    query_version: "rcx-preset-v1",
    coverage: { title: "AHU SAT", chart_kind: "timeseries", role_col: "sat" },
    points: [
      { timestamp_utc: "2024-01-01T00:00:00Z", equipment_id: "AHU_1", value: 55 },
      { timestamp_utc: "2024-01-01T00:00:00Z", equipment_id: "AHU_2", value: 57 },
    ],
    warnings: [],
  })),
}));

vi.mock("../components/widgets/PlotlyHost", () => ({
  PlotlyHost: ({
    testId,
    figureId,
  }: {
    testId?: string;
    figureId?: string;
  }) => <div data-testid={testId ?? "plotly"} data-figure-id={figureId} />,
}));

import { postRcxPreset } from "../api/analyticsApi";

describe("RcxPage", () => {
  beforeEach(() => {
    vi.mocked(postRcxPreset).mockClear();
  });

  it("auto-runs the selected plot and remounts by preset figureId", async () => {
    render(
      <MemoryRouter initialEntries={["/rcx?site=B1"]}>
        <RcxPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("rcx-page")).toBeTruthy();
      expect(
        screen.getByRole("heading", { level: 2, name: "RCx plots" }),
      ).toBeTruthy();
      expect(postRcxPreset).toHaveBeenCalled();
    });
    const host = screen.getByTestId("rcx-plot");
    expect(host.getAttribute("data-figure-id")).toBe("rcx-ahu_sat");
    expect(screen.getByTestId("rcx-family").textContent).toMatch(
      /Mechanical family/,
    );
    expect(screen.getByTestId("rcx-preset").textContent).toMatch(/^Plot/);
  });
});
