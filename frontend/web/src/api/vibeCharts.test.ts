import { describe, expect, it } from "vitest";
import {
  multiEquipmentBox,
  rankingBars,
  ruleResultChart,
  sensorFaultChart,
  sensorHealthHeatmap,
} from "./vibeCharts";

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
    expect(fig?.data.some((t) => t.name === "confirmed_fault")).toBe(true);
    expect(fig?.data.some((t) => String(t.name).includes("°F"))).toBe(true);
    expect(fig?.data.some((t) => String(t.name).includes("%"))).toBe(true);
    expect(fig?.layout?.xaxis?.title).toBe("timestamp");
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
    expect(title).toBe("fault");
    expect(last?.domain?.[0] ?? 1).toBeLessThan(0.4);
    expect(faultAxis || last).toBeTruthy();
    expect(
      fig?.data.every((t) => !String(t.name).includes("undefined")),
    ).toBe(true);
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

  it("sensorHealthHeatmap builds coverage grid", () => {
    const fig = sensorHealthHeatmap([
      { equipment_id: "AHU_1", role: "sat", coverage_pct: 90 },
      { equipment_id: "AHU_1", role: "mat", coverage_pct: 80 },
    ]);
    expect(fig?.data[0]?.type).toBe("heatmap");
  });

  it("sensorFaultChart adds fault swim lanes", () => {
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
  });
});
