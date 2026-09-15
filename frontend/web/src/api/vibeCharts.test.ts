import { describe, expect, it } from "vitest";
import {
  multiEquipmentBox,
  multiEquipmentTimeseries,
  rankingBars,
  rcxFigureHasFaultLane,
  ruleResultChart,
  comfortDonut,
  sensorFaultChart,
  sensorHealthHeatmap,
  vavHealthDonut,
  vavHealthWorstBars,
  expandFddPlotRoles,
  isOatMeteoRule,
  withConfirmedFaultLane,
} from "./vibeCharts";
import { basOverlay } from "./centralOverview";
import chartContract from "./charts.contract.json";

describe("vibeCharts", () => {
  it("ruleResultChart stacks unit families and puts fault on the bottom axis", () => {
    const fig = ruleResultChart(
      [
        {
          timestamp_utc: "2026-03-01T00:00:00Z",
          zone_t: 70,
          fan_cmd: 80,
          duct_static: 1.1,
        },
        {
          timestamp_utc: "2026-03-01T01:00:00Z",
          zone_t: 78,
          fan_cmd: 100,
          duct_static: 0.9,
        },
      ],
      {
        equipmentId: "AHU_1",
        ruleId: "FC1",
        roles: ["zone_t", "fan_cmd", "duct_static"],
        confirmedFault: [0, 1],
      },
    );
    expect(fig?.data.some((t) => t.name === chartContract.ruleResultChart.fault_trace)).toBe(
      true,
    );
    expect(fig?.layout?.xaxis?.title).toBe(
      chartContract.ruleResultChart.xaxis_title,
    );
    expect(fig?.layout?.xaxis?.type).toBe("date");
    // Fault is last y-axis (bottom domain)
    const yKeys = Object.keys(fig?.layout ?? {}).filter((k) =>
      /^yaxis\d*$/.test(k),
    );
    expect(yKeys.length).toBeGreaterThanOrEqual(3);
    const faultAxis = fig?.layout?.[`yaxis${yKeys.length}` as "yaxis"] as
      | { domain?: number[]; title?: { text?: string } }
      | undefined;
    // last axis is yaxisN
    const lastKey = yKeys.sort((a, b) => {
      const na = a === "yaxis" ? 1 : Number(a.replace("yaxis", ""));
      const nb = b === "yaxis" ? 1 : Number(b.replace("yaxis", ""));
      return na - nb;
    })[yKeys.length - 1];
    const last = fig?.layout?.[lastKey as "yaxis"] as {
      domain?: number[];
      title?: { text?: string } | string;
    };
    const title =
      typeof last?.title === "string" ? last.title : last?.title?.text;
    expect(title).toBe(chartContract.ruleResultChart.fault_axis_title);
    expect(last?.domain?.[0] ?? 1).toBeLessThan(0.4);
    expect(faultAxis || last).toBeTruthy();
    expect(
      fig?.data.every((t) => !String(t.name).includes("undefined")),
    ).toBe(true);
    const signal = (fig?.data ?? []).filter((t) => t.name !== "confirmed_fault");
    expect(signal.every((t) => t.fill == null && t.fillcolor == null)).toBe(
      true,
    );
    const fault = fig?.data.find((t) => t.name === "confirmed_fault");
    expect(fault?.fill).toBe("tozeroy");
    expect(fault?.mode).toBe("lines");
    expect(
      (last as { range?: number[] } | undefined)?.range,
    ).toEqual([-0.05, 1.15]);
  });

  it("ruleResultChart builds from optional-role-only series (SV/PID Plots)", () => {
    const roles = ["sat", "rat", "oa_damper_pct"];
    const fig = ruleResultChart(
      [
        {
          timestamp_utc: "2026-03-01T11:00:00Z",
          sat: 55,
          rat: 72,
          oa_damper_pct: 40,
        },
        {
          timestamp_utc: "2026-03-01T12:00:00Z",
          sat: 56,
          rat: 71,
          oa_damper_pct: 85,
        },
      ],
      {
        equipmentId: "AHU_1",
        ruleId: "PID-HUNT-1",
        roles,
        confirmedFault: [0, 1],
      },
    );
    expect(fig).toBeTruthy();
    expect(fig?.data.some((t) => t.name === "confirmed_fault")).toBe(true);
    expect(fig?.data.some((t) => String(t.name).toLowerCase().includes("damper"))).toBe(
      true,
    );
  });

  it("expandFddPlotRoles adds oa_damper_pct for ECON-4 when present in rows", () => {
    const roles = expandFddPlotRoles(
      "ECON-4",
      ["mat", "rat", "oa_t", "fan_cmd"],
      [
        { timestamp_utc: "t0", mat: 55, rat: 72, oa_t: 40, fan_cmd: 1, oa_damper_pct: 25 },
        { timestamp_utc: "t1", mat: 56, rat: 71, oa_t: 41, fan_cmd: 1, oa_damper_pct: 30 },
      ],
    );
    expect(roles).toContain("oa_damper_pct");
  });

  it("ECON-4 FDD figure includes damper on % axis plus confirmed_fault", () => {
    const rows = [
      {
        timestamp_utc: "2026-03-01T11:00:00Z",
        mat: 55,
        rat: 72,
        oa_t: 40,
        fan_cmd: 1,
        oa_damper_pct: 20,
      },
      {
        timestamp_utc: "2026-03-01T12:00:00Z",
        mat: 56,
        rat: 71,
        oa_t: 42,
        fan_cmd: 1,
        oa_damper_pct: 35,
      },
    ];
    const roles = expandFddPlotRoles("ECON-4", ["mat", "rat", "oa_t", "fan_cmd"], rows);
    const fig = ruleResultChart(rows, {
      equipmentId: "AHU_1",
      ruleId: "ECON-4",
      roles,
      confirmedFault: [0, 1],
    });
    expect(fig?.data.some((t) => String(t.name).includes("oa_damper_pct"))).toBe(true);
    expect(fig?.data.some((t) => t.name === "confirmed_fault")).toBe(true);
    const damper = fig?.data.find((t) => String(t.name).includes("oa_damper_pct"));
    expect(damper?.yaxis).toBe("y2");
    expect(fig?.layout?.yaxis2).toBeTruthy();
  });

  it("OAT-METEO FDD figure has BAS + Web OAT traces and confirmed_fault", () => {
    const overlay = basOverlay(
      [
        {
          timestamp_utc: "2026-07-01T00:00:00Z",
          bas_oat_f: 70,
          web_oat_f: 68,
        },
        {
          timestamp_utc: "2026-07-01T01:00:00Z",
          bas_oat_f: 72,
          web_oat_f: 69,
        },
      ],
      5,
    );
    expect(overlay).toBeTruthy();
    const fig = withConfirmedFaultLane(overlay!, {
      equipmentId: "AHU_1",
      ruleId: "OAT-METEO",
      faultX: ["2026-07-01T00:00:00Z", "2026-07-01T01:00:00Z"],
      confirmedFault: [0, 1],
    });
    const oatTraces = (fig.data ?? []).filter(
      (t) => t.name === "BAS oa_t" || t.name === "Web OAT",
    );
    expect(oatTraces.length).toBeGreaterThanOrEqual(2);
    expect(fig.data.some((t) => t.name === "confirmed_fault")).toBe(true);
    expect(isOatMeteoRule("OAT-METEO")).toBe(true);
    expect(isOatMeteoRule("weather")).toBe(true);
  });

  it("ruleResultChart rejects PrimitiveArray timestamp dumps", () => {
    const fig = ruleResultChart(
      [
        {
          timestamp_utc: "PrimitiveArray<TimestampNanosecondType>",
          zone_t: 70,
        },
      ],
      { equipmentId: "VAV_1", ruleId: "VAV-1", roles: ["zone_t"] },
    );
    expect(fig?.data[0]?.x?.[0]).toBeNull();
  });

  it("rankingBars sorts by fail pct", () => {
    const fig = rankingBars(
      [
        { equipment_id: "VAV_2", value_f: 10 },
        { equipment_id: "VAV_1", value_f: 40 },
      ],
      { title: "rank" },
    );
    expect(fig?.data[0]?.x?.[0]).toBe("VAV_1");
  });

  it("multiEquipmentBox groups by equipment", () => {
    const fig = multiEquipmentBox(
      [
        { equipment_id: "AHU_1", value_f: 1.2 },
        { equipment_id: "AHU_1", value_f: 1.4 },
        { equipment_id: "AHU_2", value_f: 0.9 },
      ],
      { title: "box" },
    );
    expect(fig?.data).toHaveLength(2);
    expect(fig?.data[0]?.type).toBe("box");
  });

  it("RCx timeseries never includes a confirmed_fault lane", () => {
    const fig = multiEquipmentTimeseries(
      [
        {
          equipment_id: "AHU_1",
          timestamp_utc: "2026-01-01T00:00:00Z",
          value_f: 55,
          series: "primary",
        },
        {
          equipment_id: "AHU_1",
          timestamp_utc: "2026-01-01T00:00:00Z",
          value_f: 1,
          series: "motor",
        },
        {
          equipment_id: "AHU_2",
          timestamp_utc: "2026-01-01T00:00:00Z",
          value_f: 58,
          series: "primary",
        },
      ],
      { title: "ahu_dats", yTitle: "°F" },
    );
    expect(rcxFigureHasFaultLane(fig)).toBe(false);
    expect(fig?.data.some((t) => t.yaxis === "y2")).toBe(true);
    expect(fig?.layout?.yaxis2).toBeTruthy();
    const y2 = fig?.layout?.yaxis2 as { title?: { text?: string } };
    expect(y2?.title?.text).toBe("motor on");
    expect(fig?.layout?.yaxis?.title).toBe("°F");
    expect(fig?.layout?.xaxis?.title).toBe("timestamp");
  });

  it("sensorHealthHeatmap builds coverage grid", () => {
    const fig = sensorHealthHeatmap([
      { equipment_id: "AHU_1", role: "sat", coverage_pct: 90 },
      { equipment_id: "AHU_1", role: "mat", coverage_pct: 80 },
    ]);
    expect(fig?.data[0]?.type).toBe("heatmap");
  });

  it("sensorFaultChart adds fault swim lanes on a bottom domain", () => {
    const points = Array.from({ length: 24 }, (_, i) => ({
      timestamp_utc: `t${i}`,
      value_f: 55,
    }));
    const fig = sensorFaultChart(points, { sensorName: "AHU_1 · sat" });
    expect(fig?.data[0]?.name).toBe("AHU_1 · sat");
    expect(
      fig?.data.some((t: { name?: string }) =>
        String(t.name).includes("FLATLINE"),
      ),
    ).toBe(true);
    const y2 = fig?.layout?.yaxis2 as { domain?: number[]; title?: string };
    expect(y2?.title).toBe("fault");
    expect(y2?.domain?.[0]).toBe(0);
    expect(y2?.domain?.[1]).toBeLessThanOrEqual(0.22);
    const y1 = fig?.layout?.yaxis as { domain?: number[] };
    expect(y1?.domain?.[0] ?? 0).toBeGreaterThan(0.2);
  });

  it("comfortDonut uses ranking rows", () => {
    const fig = comfortDonut([
      { equipment_id: "VAV_1", n_samples: 10, n_fail: 4 },
    ]);
    expect(fig?.data[0]?.type).toBe("pie");
  });

  it("vavHealthDonut buckets broken / comfort / rogue / ok", () => {
    const fig = vavHealthDonut([
      { equipment_id: "VAV_1", broken_box: true, poor_zone_performance: true },
      {
        equipment_id: "VAV_2",
        broken_box: false,
        poor_zone_performance: true,
        rogue_damper: false,
      },
      {
        equipment_id: "VAV_3",
        broken_box: false,
        poor_zone_performance: false,
        rogue_damper: true,
      },
      {
        equipment_id: "VAV_4",
        broken_box: false,
        poor_zone_performance: false,
        rogue_damper: false,
      },
      { equipment_id: "VAV_5", broken_box: null, poor_zone_performance: null },
    ]);
    expect(fig?.data[0]?.type).toBe("pie");
    expect(fig?.data[0]?.labels).toEqual([
      "broken",
      "comfort-fail",
      "rogue",
      "ok",
    ]);
    expect(fig?.data[0]?.values).toEqual([1, 1, 1, 2]);
  });

  it("vavHealthWorstBars ranks by comfort_fault_h horizontally", () => {
    const fig = vavHealthWorstBars(
      [
        { equipment_id: "VAV_lo", comfort_fault_h: 1 },
        { equipment_id: "VAV_hi", comfort_fault_h: 40 },
        { equipment_id: "VAV_mid", comfort_fault_h: 12 },
      ],
      { title: "worst" },
    );
    expect(fig?.data[0]?.type).toBe("bar");
    expect(fig?.data[0]?.orientation).toBe("h");
    // reversed for horizontal display: bottom = worst
    expect(fig?.data[0]?.y?.at(-1)).toBe("VAV_hi");
    expect(fig?.data[0]?.x?.at(-1)).toBe(40);
  });
});
