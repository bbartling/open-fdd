import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      equipment_kinds: ["vav"],
      required_roles: ["zone_t"],
      optional_roles: [],
      applicability: "typed",
      parameter_count: 0,
    },
  ]),
  listFddPlotsByRule: vi.fn(async () => ({
    ok: true,
    lean_budget: { default_points: 1500, max_roles: 6 },
    rules: [],
    soft_open_neq_fq: true,
  })),
  leanPlotDefaultPoints: (budget?: { default_points?: number } | null) => {
    const n = Number(budget?.default_points);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1500;
  },
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

import { getFddSeries, getFddResults, listFddRules } from "../api/fddApi";
import { getPackageMapping } from "../api/mappingApi";
import { listFddEquipment, postSensorHealth } from "../api/analyticsApi";

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
      expect(getFddSeries).toHaveBeenCalledWith(
        "VAV_1",
        "VAV-1",
        "B1",
        expect.objectContaining({ maxPoints: 1500, signal: expect.any(AbortSignal) }),
      );
      expect(screen.getByTestId("plots-chart")).toBeTruthy();
      expect(screen.getByTestId("plots-preview-table")).toBeTruthy();
      expect(screen.queryByTestId("plots-no-fault")).toBeNull();
    });
    // Layout/fault-lane asserts live in vibeCharts tests — never paint
    // last_axis=/domain0= debug under the plot for operators.
    expect(screen.queryByTestId("plots-fault-lane")).toBeNull();
    expect(screen.queryByText(/last_axis=/)).toBeNull();
    expect(screen.queryByText(/domain0=/)).toBeNull();
    const preview = screen.getByTestId("plots-preview-table");
    expect(preview.querySelector("tbody td")?.textContent).toBe(
      "2024-01-01T00:05:00Z",
    );
    expect(
      screen.getByTestId("plots-preview-rows").querySelector("select")?.value,
    ).toBe("10");
    expect(screen.queryByText(/first rows/i)).toBeNull();
  });

  it("previews the newest samples and changes only this plot's row count", async () => {
    const rows = Array.from({ length: 15 }, (_, i) => ({
      timestamp_utc: `2024-02-01T00:${String(i).padStart(2, "0")}:00Z`,
      zone_t: 60 + i,
      confirmed_fault: i === 14 ? 1 : 0,
    }));
    vi.mocked(getFddSeries).mockResolvedValue({
      ok: true,
      equipment_id: "VAV_1",
      rule_id: "VAV-1",
      roles: ["zone_t"],
      rows,
      downsampled: false,
      max_points: 5000,
      has_confirmed_fault: true,
    });
    renderPlots();
    await waitFor(() => {
      expect(
        screen.getByTestId("plots-preview-table").querySelector("tbody td")
          ?.textContent,
      ).toBe("2024-02-01T00:14:00Z");
    });
    const table = screen.getByTestId("plots-preview-table");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(10);
    const select = screen.getByTestId("plots-preview-rows").querySelector("select");
    expect([...(select?.options ?? [])].map((o) => o.value)).toEqual([
      "10",
      "20",
      "50",
      "100",
      "500",
    ]);
    fireEvent.change(select!, { target: { value: "20" } });
    expect(table.querySelectorAll("tbody tr")).toHaveLength(15);
    expect(table.querySelector("tbody td")?.textContent).toBe(
      "2024-02-01T00:14:00Z",
    );
    expect(screen.getByText("Series preview (most recent 20)")).toBeTruthy();
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
        /per-sample confirmed_fault|Soft-OPEN overlay gap/,
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
        equipment_kinds: ["ahu"],
        required_roles: ["oa_t"],
        optional_roles: ["web_oa_t"],
        applicability: "typed",
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

const FAMILY_CATALOG = [
  {
    rule_id: "FC5",
    description: "SAT cold when heating commanded (GL36 D)",
    equipment_kinds: ["ahu"],
    required_roles: ["sat", "mat", "htg_valve_pct", "fan_cmd"],
    optional_roles: ["fan_status", "fan_cmd"],
    applicability: "typed" as const,
  },
  {
    rule_id: "FC6",
    description: "Estimated OA fraction mismatch",
    equipment_kinds: ["ahu"],
    required_roles: ["mat", "rat", "oa_t", "fan_cmd", "vav_total_flow"],
    optional_roles: ["fan_status", "fan_cmd"],
    applicability: "typed" as const,
  },
  {
    rule_id: "VAV-3",
    description: "Excessive reheat during warm weather",
    equipment_kinds: ["vav"],
    required_roles: ["oa_t", "reheat_valve_pct", "zone_flow"],
    optional_roles: ["fan_status", "fan_cmd"],
    applicability: "typed" as const,
  },
  {
    rule_id: "TRIM-3",
    description: "HWST trim advisory",
    equipment_kinds: ["boiler"],
    required_roles: ["hw_supply_t"],
    optional_roles: ["pump_status"],
    applicability: "typed" as const,
  },
  {
    rule_id: "SITE-ROLLUP",
    description: "Applies to every equipment type",
    equipment_kinds: [],
    required_roles: [],
    optional_roles: [],
    applicability: "all" as const,
  },
  {
    rule_id: "W4A-UNKNOWN",
    description: "Must not be offered",
    equipment_kinds: ["ahu", "vav", "boiler"],
    required_roles: ["sat", "fan_status", "hw_supply_t"],
    optional_roles: ["fan_cmd"],
    applicability: "unknown" as const,
  },
];

function optionValues(testId: string): string[] {
  const select = screen.getByTestId(testId).querySelector("select");
  return [...(select?.options ?? [])].map((option) => option.value);
}

describe("ReportsPage rule eligibility", () => {
  beforeEach(() => {
    vi.mocked(listFddRules).mockResolvedValue(FAMILY_CATALOG);
    vi.mocked(getFddResults).mockResolvedValue([]);
    vi.mocked(getFddSeries).mockClear();
  });

  it("offers AHU, VAV, and boiler rules only when type and roles match", async () => {
    const cases = [
      {
        id: "AHU_1",
        type: "AHU",
        roles: ["sat", "mat", "htg_valve_pct", "fan_cmd", "fan_status"],
        offered: ["FC5", "SITE-ROLLUP"],
        withheld: ["FC6", "VAV-3", "TRIM-3", "W4A-UNKNOWN"],
        series: "FC5",
        notice: /FC6 is not eligible: missing mapped roles .*vav_total_flow/,
      },
      {
        id: "RTU_2",
        type: "RTU",
        roles: ["sat", "mat", "htg_valve_pct", "fan_cmd", "fan_status"],
        offered: ["FC5", "SITE-ROLLUP"],
        withheld: ["VAV-3", "TRIM-3", "W4A-UNKNOWN"],
        series: "FC5",
        notice: /unknown applicability/,
      },
      {
        id: "VAV_1",
        type: "VAV",
        roles: ["oa_t", "reheat_valve_pct", "zone_flow", "fan_status"],
        offered: ["VAV-3", "SITE-ROLLUP"],
        withheld: ["FC5", "FC6", "TRIM-3", "W4A-UNKNOWN"],
        series: "VAV-3",
        notice: /unknown applicability/,
      },
      {
        id: "BLR_1",
        type: "boiler",
        roles: ["hw_supply_t"],
        offered: ["TRIM-3", "SITE-ROLLUP"],
        withheld: ["FC5", "FC6", "VAV-3", "W4A-UNKNOWN"],
        series: "TRIM-3",
        notice: /unknown applicability/,
      },
    ];

    for (const sample of cases) {
      vi.mocked(getFddSeries).mockClear();
      vi.mocked(getPackageMapping).mockResolvedValue({
        ok: true,
        building_id: "B1",
        equipment: [
          {
            equipment_id: sample.id,
            equipment_type: sample.type,
            ok: true,
            roles: Object.fromEntries(sample.roles.map((role) => [role, role])),
            columns: sample.roles.map((role) => ({
              column: role,
              role,
              status: "mapped",
            })),
          },
        ],
      } as never);
      vi.mocked(listFddEquipment).mockResolvedValue([
        { equipment_id: sample.id, equipment_type: sample.type },
      ]);
      const view = renderPlots(`/reports?site=B1&eq=${sample.id}`);
      await waitFor(() => {
        expect(optionValues("plots-rule-select")).toEqual(["", ...sample.offered]);
      });
      for (const withheld of sample.withheld) {
        expect(optionValues("plots-rule-select")).not.toContain(withheld);
      }
      expect(screen.getByTestId("plots-rule-eligibility").textContent).toMatch(
        sample.notice,
      );
      await waitFor(() => {
        expect(getFddSeries).toHaveBeenCalledWith(
          sample.id,
          sample.series,
          "B1",
          expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
      });
      const requested = vi.mocked(getFddSeries).mock.calls.map((call) => call[1]);
      for (const withheld of sample.withheld) {
        expect(requested).not.toContain(withheld);
      }
      if (sample.id === "AHU_1") {
        expect(screen.getByTestId("plots-rule-select").textContent).toMatch(
          /SAT cold when heating commanded/,
        );
        expect(screen.getByTestId("plots-rule-select").textContent).not.toMatch(
          /Boiler/,
        );
      }
      view.unmount();
    }
  });
});

async function openSensorHealth() {
  renderPlots();
  await waitFor(() => {
    expect(screen.getByTestId("sensor-health-expander")).toBeTruthy();
  });
  fireEvent.click(screen.getByRole("button", { name: /Sensor health/ }));
  fireEvent.click(screen.getByRole("button", { name: "Load sensor health" }));
}

describe("ReportsPage sensor health", () => {
  beforeEach(() => {
    vi.mocked(postSensorHealth).mockReset();
  });

  it("shows historian rows for the locked site and equipment", async () => {
    vi.mocked(postSensorHealth).mockResolvedValue({
      schema_version: "analytics-envelope-v1",
      query_version: "sensor-health-v1",
      generated_at: "",
      engine: "timescale-sql",
      warnings: [],
      coverage: { source: "timescale_sample", series_count: 1, point_count: 8 },
      rows: [
        {
          building_id: "B1",
          equipment_id: "VAV_1",
          role: "zone_t",
          n: 8,
          n_finite: 8,
          coverage_pct: 100,
          missingness: 0,
          flatline_flag: false,
          mean: 70.5,
          std: 0.5,
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
    });
    await openSensorHealth();
    await waitFor(() => {
      expect(screen.getByTestId("sensor-health-table").textContent).toMatch(/VAV_1/);
    });
    expect(screen.getByTestId("sensor-health-table").textContent).toMatch(/zone_t/);
    expect(screen.getByTestId("sensor-health-table").textContent).toMatch(/100/);
    expect(screen.queryByTestId("inline-alert-sensor-health-error")).toBeNull();
    expect(screen.queryByTestId("inline-alert-sensor-health-empty")).toBeNull();
    expect(screen.queryByText(/historian\/job sensor-health load is next/)).toBeNull();
    const body = vi.mocked(postSensorHealth).mock.calls.at(-1)?.[0];
    expect(body).toMatchObject({
      building_id: "B1",
      equipment_ids: ["VAV_1"],
    });
    expect(body?.series).toBeUndefined();
  });

  it("shows an empty window without a historian error", async () => {
    vi.mocked(postSensorHealth).mockResolvedValue({
      schema_version: "analytics-envelope-v1",
      query_version: "sensor-health-v1",
      generated_at: "",
      engine: "timescale-sql",
      warnings: ["no samples in the requested window"],
      coverage: { reason: "no_samples_in_window", series_count: 0, point_count: 0 },
      rows: [],
      equipment: [],
      points: [],
      skipped: [],
    });
    await openSensorHealth();
    await waitFor(() => {
      expect(screen.getByTestId("inline-alert-sensor-health-empty").textContent).toMatch(
        /No samples in the requested window/,
      );
    });
    expect(screen.queryByTestId("sensor-health-table")).toBeNull();
    expect(screen.queryByTestId("inline-alert-sensor-health-error")).toBeNull();
    expect(screen.queryByText(/historian\/job sensor-health load is next/)).toBeNull();
  });

  it("surfaces a historian failure instead of an empty success", async () => {
    vi.mocked(postSensorHealth).mockRejectedValue(
      new Error("sensor health historian query failed"),
    );
    await openSensorHealth();
    await waitFor(() => {
      expect(screen.getByTestId("inline-alert-sensor-health-error").textContent).toMatch(
        /sensor health historian query failed/,
      );
    });
    expect(screen.queryByTestId("sensor-health-table")).toBeNull();
    expect(screen.queryByTestId("inline-alert-sensor-health-empty")).toBeNull();
    expect(screen.queryByText(/historian\/job sensor-health load is next/)).toBeNull();
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
