import { describe, expect, it } from "vitest";
import { fileToDataset, mergeDatasets, parseCsvText, type CsvDataset } from "./csvWorkbench";

describe("csvWorkbench", () => {
  it("parses header and counts rows", () => {
    const text = "Date,Temp\n2024-01-01,72\n2024-01-02,70\n";
    const p = parseCsvText(text);
    expect(p.columns).toEqual(["Date", "Temp"]);
    expect(p.rowCount).toBe(2);
    expect(p.allRows.length).toBe(2);
    expect(p.timestampColumn).toBe("Date");
  });

  it("fileToDataset keeps all rows beyond preview sample", () => {
    const rows = Array.from({ length: 1200 }, (_, i) => `2024-01-${String(i + 1).padStart(2, "0")},${i}`);
    const text = `Date,Temp\n${rows.join("\n")}\n`;
    const ds = fileToDataset({ name: "big.csv", size: text.length } as File, text, 50);
    expect(ds.rowCount).toBe(1200);
    expect(ds.allRows.length).toBe(1200);
    expect(ds.rows.length).toBe(50);
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
      allRows: [
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
      allRows: [
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

  it("inner merge excludes keys only present in one dataset", () => {
    const a: CsvDataset = {
      id: "a",
      name: "a.csv",
      columns: ["Date", "Temp"],
      rows: [["2024-01-01", "72"]],
      allRows: [
        ["2024-01-01", "72"],
        ["2024-01-03", "68"],
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
      rows: [["2024-01-01", "45"]],
      allRows: [["2024-01-01", "45"]],
      rowCount: 1,
      bytes: 1,
      timestampColumn: "Date",
      fullText: "",
    };
    const merged = mergeDatasets([a, b], "Date", "inner");
    expect(merged.rowCount).toBe(1);
    expect(merged.rows[0][0]).toBe("2024-01-01");
  });
});
