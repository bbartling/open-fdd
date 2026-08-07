import { describe, expect, it } from "vitest";
import { monthlyLines, stackedFuel } from "./fuelCharts";

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
});
