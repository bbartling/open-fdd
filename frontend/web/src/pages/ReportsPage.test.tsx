import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReportsPage } from "./ReportsPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    building_id: "B1",
    equipment: [
      {
        equipment_id: "VAV_1",
        equipment_type: "VAV",
        ok: true,
        roles: { zone_t: "zone_t" },
        columns: [{ column: "zone_air_temp", role: "zone_t", status: "mapped" }],
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: {} })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => [
    {
      rule_id: "VAV-1",
      description: "Comfort",
      required_roles: ["zone_t"],
      parameter_count: 0,
    },
  ]),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
  getFddResults: vi.fn(async () => [
    { rule_id: "VAV-1", equipment_id: "VAV_1", status: "FAULT" },
  ]),
  getFddSeries: vi.fn(async () => ({
    ok: true,
    equipment_id: "VAV_1",
    rule_id: "VAV-1",
    roles: ["zone_t"],
    rows: [
      { timestamp_utc: "2024-01-01T00:00:00Z", zone_t: 70, confirmed_fault: 0 },
      { timestamp_utc: "2024-01-01T00:05:00Z", zone_t: 71, confirmed_fault: 1 },
    ],
    downsampled: false,
    max_points: 5000,
    has_confirmed_fault: true,
  })),
}));

vi.mock("../api/analyticsApi", () => ({
  listFddEquipment: vi.fn(async () => [
    { equipment_id: "VAV_1", equipment_type: "VAV" },
  ]),
  postSensorHealth: vi.fn(async () => ({
    schema_version: "analytics-envelope-v1",
    query_version: "sensor-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postInspect: vi.fn(async () => ({
    points: [],
    warnings: [],
  })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

import { getFddSeries, getFddResults } from "../api/fddApi";

function renderPlots(entry = "/reports?site=B1&eq=VAV_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ReportsPage />
    </MemoryRouter>,
  );
}

describe("ReportsPage FDD Plots", () => {
  beforeEach(() => {
    vi.mocked(getFddSeries).mockClear();
    vi.mocked(getFddResults).mockReset();
    vi.mocked(getFddResults).mockResolvedValue([
      { rule_id: "VAV-1", equipment_id: "VAV_1", status: "FAULT" },
    ]);
    vi.mocked(getFddSeries).mockResolvedValue({
      ok: true,
      equipment_id: "VAV_1",
      rule_id: "VAV-1",
      roles: ["zone_t"],
      rows: [
        { timestamp_utc: "2024-01-01T00:00:00Z", zone_t: 70, confirmed_fault: 0 },
        { timestamp_utc: "2024-01-01T00:05:00Z", zone_t: 71, confirmed_fault: 1 },
      ],
      downsampled: false,
      max_points: 5000,
      has_confirmed_fault: true,
    });
  });

  it("shows FDD Plots title without artifacts mode or building reselect", async () => {
    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-page")).toBeTruthy();
    });
    expect(screen.getByRole("heading", { level: 1, name: "FDD Plots" })).toBeTruthy();
    expect(screen.queryByTestId("reports-mode")).toBeNull();
    expect(screen.queryByTestId("plots-building-select")).toBeNull();
    expect(screen.getByTestId("locked-site").textContent).toMatch(/zip:B1/);
    expect(screen.getByTestId("plots-device-type")).toBeTruthy();
    expect(screen.getByTestId("plots-status-filter")).toBeTruthy();
  });

  it("auto-loads series and puts confirmed_fault on the bottom lane", async () => {
    renderPlots();
    await waitFor(() => {
      expect(getFddSeries).toHaveBeenCalledWith("VAV_1", "VAV-1", "B1");
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
      expect(screen.getByTestId("plots-preview-table")).toBeTruthy();
      expect(screen.queryByTestId("plots-no-fault")).toBeNull();
    });
    const meta = screen.getByTestId("plots-fault-lane").textContent ?? "";
    expect(meta).toMatch(/last_axis=fault/);
    expect(meta).toMatch(/last_trace=confirmed_fault/);
    const domain0 = Number(meta.match(/domain0=([0-9.]+)/)?.[1] ?? "1");
    expect(domain0).toBeLessThan(0.4);
  });

  it("fails when results exist but confirmed_fault overlay is absent", async () => {
    const { getFddResults } = await import("../api/fddApi");
    vi.mocked(getFddResults).mockResolvedValue([
      { rule_id: "VAV-1", equipment_id: "VAV_1", status: "PASS", fault_hours: 0 },
    ]);
    vi.mocked(getFddSeries).mockResolvedValue({
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
      has_confirmed_fault: false,
    });
    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-no-fault").textContent).toMatch(
        /timestamp join failed/,
      );
    });
  });

  it("flags FAULT results when the series window has 0 confirmed_fault trues", async () => {
    vi.mocked(getFddSeries).mockResolvedValue({
      ok: true,
      equipment_id: "VAV_1",
      rule_id: "VAV-1",
      roles: ["zone_t"],
      rows: [
        { timestamp_utc: "2024-01-01T00:00:00Z", zone_t: 70, confirmed_fault: false },
        { timestamp_utc: "2024-01-01T00:05:00Z", zone_t: 71, confirmed_fault: false },
      ],
      downsampled: false,
      max_points: 5000,
      has_confirmed_fault: false,
    });
    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-no-fault").textContent).toMatch(
        /0 confirmed_fault trues/,
      );
    });
  });
});
