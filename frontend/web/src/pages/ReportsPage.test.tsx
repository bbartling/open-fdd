import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReportsPage } from "./ReportsPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => [
    { rule_id: "VAV-1", description: "Comfort", required_roles: ["zone_t"] },
  ]),
  getFddResults: vi.fn(async () => [
    { rule_id: "VAV-1", equipment_id: "VAV_1", status: "FAULT" },
  ]),
  getFddSeries: vi.fn(async () => ({
    ok: true,
    equipment_id: "VAV_1",
    rule_id: "VAV-1",
    roles: ["zone_t"],
    rows: [
      { timestamp_utc: "2024-01-01T00:00:00Z", zone_t: 70 },
      { timestamp_utc: "2024-01-01T00:05:00Z", zone_t: 71 },
    ],
    downsampled: false,
    max_points: 5000,
  })),
}));

import { getFddSeries } from "../api/fddApi";

function renderPlots(entry = "/reports?site=B1&eq=VAV_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ReportsPage />
    </MemoryRouter>,
  );
}

describe("ReportsPage plots", () => {
  beforeEach(() => {
    vi.mocked(getFddSeries).mockClear();
  });

  it("loads series and renders chart + preview", async () => {
    renderPlots();
    await waitFor(() => screen.getByTestId("plots-load"));
    fireEvent.click(screen.getByTestId("plots-load").querySelector("button")!);
    await waitFor(() => {
      expect(getFddSeries).toHaveBeenCalledWith("VAV_1", "VAV-1");
      expect(screen.getByTestId("plotly-svg-fdd-series")).toBeTruthy();
      expect(screen.getByTestId("plots-preview-table")).toBeTruthy();
    });
  });
});
