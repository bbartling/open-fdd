import { describe, expect, it } from "vitest";
import {
  multiEquipmentBox,
  rankingBars,
  ruleResultChart,
  sensorFaultChart,
  sensorHealthHeatmap,
} from "./vibeCharts";

describe("vibeCharts", () => {
  it("ruleResultChart adds confirmed_fault swim lane", () => {
    const fig = ruleResultChart(
      [
        { timestamp_utc: "t0", zone_t: 70, confirmed_fault: 0 },
        { timestamp_utc: "t1", zone_t: 78, confirmed_fault: 1 },
      ],
      {
        equipmentId: "VAV_1",
        ruleId: "VAV-1",
        roles: ["zone_t"],
        confirmedFault: [0, 1],
      },
    );
    expect(fig?.data.some((t) => t.name === "confirmed_fault")).toBe(true);
    expect(fig?.layout?.yaxis2).toBeTruthy();
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
