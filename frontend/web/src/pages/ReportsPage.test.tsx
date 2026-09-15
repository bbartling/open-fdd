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
  postBasVsWebOat: vi.fn(async () => ({
    points: [
      {
        timestamp_utc: "2024-01-01T00:00:00Z",
        bas_oat_f: 40,
        web_oat_f: 42,
      },
      {
        timestamp_utc: "2024-01-01T00:05:00Z",
        bas_oat_f: 41,
        web_oat_f: 43,
      },
    ],
    rows: [],
    warnings: [],
  })),
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
    expect(screen.queryByTestId("plots-status-filter")).toBeNull();
    await waitFor(() => {
      expect(screen.getByTestId("plots-zone-comfort-gate")).toBeTruthy();
    });
  });

  it("auto-loads series without developer fault-lane debug chrome", async () => {
    renderPlots();
    await waitFor(() => {
      expect(getFddSeries).toHaveBeenCalledWith("VAV_1", "VAV-1", "B1");
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
      expect(screen.getByTestId("plots-preview-table")).toBeTruthy();
      expect(screen.queryByTestId("plots-no-fault")).toBeNull();
    });
    // Layout/fault-lane asserts live in vibeCharts tests — never paint
    // last_axis=/domain0= debug under the plot for operators.
    expect(screen.queryByTestId("plots-fault-lane")).toBeNull();
    expect(screen.queryByText(/last_axis=/)).toBeNull();
    expect(screen.queryByText(/domain0=/)).toBeNull();
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

  it("OAT-METEO loads bas-vs-web-oat overlay (not local-only series)", async () => {
    const { listFddRules } = await import("../api/fddApi");
    const { postBasVsWebOat } = await import("../api/analyticsApi");
    const { getPackageMapping } = await import("../api/mappingApi");
    const { listFddEquipment } = await import("../api/analyticsApi");

    vi.mocked(listFddRules).mockResolvedValue([
      {
        rule_id: "OAT-METEO",
        description: "Equipment OAT vs weather",
        required_roles: ["oa_t"],
        optional_roles: ["web_oa_t"],
        parameter_count: 0,
      },
    ]);
    vi.mocked(getPackageMapping).mockResolvedValue({
      ok: true,
      building_id: "B1",
      equipment: [
        {
          equipment_id: "AHU_1",
          equipment_type: "AHU",
          ok: true,
          roles: { oa_t: "oa_t" },
          columns: [{ column: "oa_t", role: "oa_t", status: "mapped" }],
        },
      ],
    } as never);
    vi.mocked(listFddEquipment).mockResolvedValue([
      { equipment_id: "AHU_1", equipment_type: "AHU" },
    ]);
    vi.mocked(getFddResults).mockResolvedValue([
      { rule_id: "OAT-METEO", equipment_id: "AHU_1", status: "FAULT", fault_hours: 2 },
    ]);
    vi.mocked(getFddSeries).mockResolvedValue({
      ok: true,
      equipment_id: "AHU_1",
      rule_id: "OAT-METEO",
      roles: ["oa_t"],
      rows: [
        { timestamp_utc: "2024-01-01T00:00:00Z", oa_t: 40, confirmed_fault: 0 },
        { timestamp_utc: "2024-01-01T00:05:00Z", oa_t: 55, confirmed_fault: 1 },
      ],
      downsampled: false,
      max_points: 5000,
      has_confirmed_fault: true,
    });

    renderPlots("/reports?site=B1&eq=AHU_1");
    await waitFor(() => {
      expect(postBasVsWebOat).toHaveBeenCalled();
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
    });
    const call = vi.mocked(postBasVsWebOat).mock.calls.at(-1)?.[0] as {
      building_id?: string;
    };
    expect(call?.building_id).toBe("B1");
  });
});

describe("FDD weather + econ helpers", () => {
  it("expandFddPlotRoles appends oa_damper_pct for ECON when column present", async () => {
    const { expandFddPlotRoles } = await import("../api/vibeCharts");
    expect(
      expandFddPlotRoles(
        "ECON-4",
        ["mat", "rat", "oa_t"],
        [{ oa_damper_pct: 40 }, { oa_damper_pct: 55 }],
      ),
    ).toEqual(["mat", "rat", "oa_t", "oa_damper_pct"]);
    expect(expandFddPlotRoles("ECON-4", ["mat"], [{ mat: 60 }])).toEqual(["mat"]);
    expect(
      expandFddPlotRoles("VAV-1", ["zone_t"], [{ oa_damper_pct: 10 }]),
    ).toEqual(["zone_t"]);
  });

  it("withConfirmedFaultLane keeps BAS+web traces and adds fault lane", async () => {
    const { withConfirmedFaultLane } = await import("../api/vibeCharts");
    const { basOverlay } = await import("../api/centralOverview");
    const overlay = basOverlay(
      [
        { timestamp_utc: "t0", bas_oat_f: 40, web_oat_f: 42 },
        { timestamp_utc: "t1", bas_oat_f: 41, web_oat_f: 43 },
      ],
      5,
    )!;
    const fig = withConfirmedFaultLane(overlay, {
      equipmentId: "AHU_1",
      ruleId: "OAT-METEO",
      faultX: ["t0", "t1"],
      confirmedFault: [0, 1],
    });
    const names = fig.data.map((t) => String(t.name ?? ""));
    expect(names.some((n) => /BAS/i.test(n))).toBe(true);
    expect(names.some((n) => /Web OAT/i.test(n))).toBe(true);
    expect(names).toContain("confirmed_fault");
    expect(fig.layout?.yaxis2).toBeTruthy();
  });
});
