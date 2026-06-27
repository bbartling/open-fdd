import { describe, expect, it } from "vitest";
import { mergeDatasets, parseCsvText, type CsvDataset } from "./csvWorkbench";

describe("csvWorkbench", () => {
  it("parses header and counts rows", () => {
    const text = "Date,Temp\n2024-01-01,72\n2024-01-02,70\n";
    const p = parseCsvText(text);
    expect(p.columns).toEqual(["Date", "Temp"]);
    expect(p.rowCount).toBe(2);
    expect(p.timestampColumn).toBe("Date");
  });

  it("inner-merges on Date", () => {
    const a: CsvDataset = {
      id: "a",
      name: "a.csv",
      columns: ["Date", "Temp"],
      rows: [
        ["2024-01-01", "72"],
        ["2024-01-02", "70"],
      ],
      rowCount: 2,
      bytes: 1,
      timestampColumn: "Date",
      fullText: "",
    };
    const b: CsvDataset = {
      id: "b",
      name: "b.csv",
      columns: ["Date", "Humidity"],
      rows: [
        ["2024-01-01", "45"],
        ["2024-01-02", "50"],
      ],
      rowCount: 2,
      bytes: 1,
      timestampColumn: "Date",
      fullText: "",
    };
    const merged = mergeDatasets([a, b], "Date", "inner");
    expect(merged.rowCount).toBe(2);
    expect(merged.columns).toContain("Humidity");
  });
});
