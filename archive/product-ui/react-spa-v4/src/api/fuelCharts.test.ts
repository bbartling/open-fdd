import { describe, expect, it } from "vitest";
import {
  monthlyLines,
  rankedSiteEui,
  rolling12Eui,
  stackedFuel,
  summaryPeerBullet,
  weatherResidualBars,
  weatherScatter,
} from "./fuelCharts";

describe("fuelCharts", () => {
  it("stackedFuel builds one trace per fuel with month x and kbtu y", () => {
    const fig = stackedFuel([
      { month: "2024-01", fuel: "electricity", kbtu: 100 },
      { month: "2024-01", fuel: "gas", kbtu: 50 },
      { month: "2024-02", fuel: "electricity", kbtu: 120 },
      { month: "2024-02", fuel: "gas", kbtu: 40 },
    ]);
    expect(fig).toBeTruthy();
    expect(fig!.data).toHaveLength(2);
    expect(fig!.data.every((t) => t.type === "bar")).toBe(true);
    const elec = fig!.data.find((t) => t.name === "electricity");
    expect(elec?.x).toEqual(["2024-01", "2024-02"]);
    expect(elec?.y).toEqual([100, 120]);
    expect(fig!.layout?.barmode).toBe("stack");
  });

  it("monthlyLines builds one line trace per meter", () => {
    const fig = monthlyLines([
      { month: "2024-01", meter_id: "M_ELEC", usage: 10, kbtu: 34 },
      { month: "2024-02", meter_id: "M_ELEC", usage: 12, kbtu: 41 },
      { month: "2024-01", meter_id: "M_GAS", usage: 2, kbtu: 200 },
      { month: "2024-02", meter_id: "M_GAS", usage: 3, kbtu: 300 },
    ]);
    expect(fig).toBeTruthy();
    expect(fig!.data).toHaveLength(2);
    expect(fig!.data.every((t) => t.type === "scatter")).toBe(true);
    const elec = fig!.data.find((t) => t.name === "M_ELEC");
    expect(elec?.x).toEqual(["2024-01", "2024-02"]);
    expect(elec?.y).toEqual([10, 12]);
  });

  it("summaryPeerBullet draws site EUI with p20–p80 band", () => {
    const fig = summaryPeerBullet([
      {
        building_id: "B1",
        site_eui_kbtu_ft2: 70,
        peer: { p20: 40, p50: 55, p80: 80 },
      },
      {
        building_id: "B2",
        site_eui_kbtu_ft2: 90,
        peer: { p20: 40, p50: 55, p80: 80 },
      },
    ]);
    expect(fig).toBeTruthy();
    expect(fig!.data.some((t) => t.name === "site_eui")).toBe(true);
    expect(fig!.data.some((t) => String(t.name).includes("p20"))).toBe(true);
  });

  it("rankedSiteEui sorts highest EUI first", () => {
    const fig = rankedSiteEui([
      { building_id: "low", site_eui: 40 },
      { building_id: "high", site_eui: 120 },
    ]);
    expect(fig).toBeTruthy();
    expect(fig!.data[0]?.y?.[0]).toBe("high");
    expect(fig!.data[0]?.x?.[0]).toBe(120);
  });

  it("rolling12Eui needs 12 months and area", () => {
    const continuous = Array.from({ length: 14 }, (_, i) => {
      const d = new Date(Date.UTC(2023, i, 1));
      const m = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
      return { month: m, kbtu: 1000 };
    });
    expect(rolling12Eui(continuous.slice(0, 5), 10000)).toBeNull();
    const fig = rolling12Eui(continuous, 10000);
    expect(fig).toBeTruthy();
    expect(fig!.data[0]?.name).toBe("roll_12_eui");
  });

  it("weatherScatter adds OLS fit line when fits provided", () => {
    const points = [
      { fuel: "gas", month: "2024-01", x: 10, y: 100, x_name: "hdd" },
      { fuel: "gas", month: "2024-02", x: 20, y: 150, x_name: "hdd" },
      { fuel: "gas", month: "2024-03", x: 30, y: 200, x_name: "hdd" },
    ];
    const fig = weatherScatter(points, [
      { fuel: "gas", slope: 5, intercept: 50, r2: 0.99 },
    ]);
    expect(fig).toBeTruthy();
    expect(fig!.data.some((t) => String(t.name).includes("fit"))).toBe(true);
    const resid = weatherResidualBars(points, {
      fuel: "gas",
      slope: 5,
      intercept: 50,
    });
    expect(resid).toBeTruthy();
    expect(resid!.data[0]?.type).toBe("bar");
  });
});
