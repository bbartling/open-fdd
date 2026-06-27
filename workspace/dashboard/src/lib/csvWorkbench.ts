/** Client-side CSV parsing and merge for the UT3-style workbench (preview + export). */

export type CsvDataset = {
  id: string;
  name: string;
  columns: string[];
  /** Sample rows for UI preview (capped). */
  rows: string[][];
  /** All parsed data rows for merge/export/commit. */
  allRows: string[][];
  rowCount: number;
  bytes: number;
  timestampColumn: string | null;
  /** Full file text for historian upload (not shown in UI). */
  fullText: string;
};

export type MergeMode = "inner" | "append";

export type ParsedCsvPreview = {
  columns: string[];
  sampleRows: string[][];
  allRows: string[][];
  rowCount: number;
  timestampColumn: string | null;
};

const TS_CANDIDATES = [
  "datetime",
  "date",
  "timestamp",
  "time",
  "ts",
  "Date",
  "Datetime",
  "Timestamp",
];

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (ch === "," && !inQuotes) {
      out.push(cur.trim());
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur.trim());
  return out;
}

function detectTimestampColumn(columns: string[]): string | null {
  for (const c of columns) {
    const lower = c.toLowerCase();
    if (TS_CANDIDATES.some((t) => lower === t.toLowerCase() || lower.includes("date") || lower.includes("time"))) {
      return c;
    }
  }
  return columns[0] ?? null;
}

function dataRowsFromText(text: string): { columns: string[]; allRows: string[][] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (!lines.length) {
    return { columns: [], allRows: [] };
  }
  const columns = splitCsvLine(lines[0]);
  const allRows: string[][] = [];
  for (let i = 1; i < lines.length; i++) {
    const row = splitCsvLine(lines[i]);
    if (row.every((c) => c === "")) continue;
    allRows.push(row);
  }
  return { columns, allRows };
}

/** Parse CSV text — keeps all rows; sample capped for UI. */
export function parseCsvText(text: string, maxSampleRows = 200): ParsedCsvPreview {
  const { columns, allRows } = dataRowsFromText(text);
  return {
    columns,
    sampleRows: allRows.slice(0, maxSampleRows),
    allRows,
    rowCount: allRows.length,
    timestampColumn: detectTimestampColumn(columns),
  };
}

export function fileToDataset(file: File, text: string, maxSampleRows = 500): CsvDataset {
  const parsed = parseCsvText(text, maxSampleRows);
  return {
    id: `ds-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: file.name,
    columns: parsed.columns,
    rows: parsed.sampleRows,
    allRows: parsed.allRows,
    rowCount: parsed.rowCount,
    bytes: file.size,
    timestampColumn: parsed.timestampColumn,
    fullText: text,
  };
}

function datasetRows(ds: CsvDataset): string[][] {
  return ds.allRows.length ? ds.allRows : ds.rows;
}

function rowToCsv(cells: string[]): string {
  return cells
    .map((c) => {
      if (c.includes(",") || c.includes('"') || c.includes("\n")) {
        return `"${c.replace(/"/g, '""')}"`;
      }
      return c;
    })
    .join(",");
}

export function datasetsToCsv(columns: string[], rows: string[][]): string {
  const header = rowToCsv(columns);
  const body = rows.map((r) => rowToCsv(r)).join("\n");
  return `${header}\n${body}`;
}

/** Merge datasets on a shared key column (inner join) or append rows with aligned columns. */
export function mergeDatasets(
  datasets: CsvDataset[],
  keyColumn: string,
  mode: MergeMode,
): { columns: string[]; rows: string[][]; rowCount: number } {
  if (!datasets.length) {
    return { columns: [], rows: [], rowCount: 0 };
  }
  if (mode === "append" || datasets.length === 1) {
    const colSet = new Set<string>();
    for (const ds of datasets) {
      for (const c of ds.columns) colSet.add(c);
    }
    const columns = [...colSet];
    const rows: string[][] = [];
    for (const ds of datasets) {
      for (const row of datasetRows(ds)) {
        const mapped = columns.map((col) => {
          const idx = ds.columns.indexOf(col);
          return idx >= 0 ? row[idx] ?? "" : "";
        });
        rows.push(mapped);
      }
    }
    return { columns, rows, rowCount: rows.length };
  }

  const [first, ...rest] = datasets;
  const firstRows = datasetRows(first);
  const keyIdx0 = first.columns.indexOf(keyColumn);
  if (keyIdx0 < 0) {
    throw new Error(`Key column "${keyColumn}" not found in ${first.name}`);
  }

  const mergedColumns = [...first.columns];
  for (const ds of rest) {
    for (const c of ds.columns) {
      if (c === keyColumn) continue;
      const suffixed = mergedColumns.includes(c) ? `${c} (${ds.name})` : c;
      if (!mergedColumns.includes(suffixed)) mergedColumns.push(suffixed);
    }
  }

  const indexMaps = rest.map((ds) => {
    const keyIdx = ds.columns.indexOf(keyColumn);
    if (keyIdx < 0) throw new Error(`Key column "${keyColumn}" not found in ${ds.name}`);
    const byKey = new Map<string, string[]>();
    for (const row of datasetRows(ds)) {
      byKey.set(row[keyIdx] ?? "", row);
    }
    return { ds, keyIdx, byKey };
  });

  const rows: string[][] = [];
  for (const row of firstRows) {
    const key = row[keyIdx0] ?? "";
    let matchedAll = true;
    for (const { byKey } of indexMaps) {
      if (!byKey.has(key)) {
        matchedAll = false;
        break;
      }
    }
    if (!matchedAll) continue;

    const out = mergedColumns.map((col) => {
      if (first.columns.includes(col)) {
        const i = first.columns.indexOf(col);
        return row[i] ?? "";
      }
      for (const { ds, byKey } of indexMaps) {
        const other = byKey.get(key);
        if (!other) return "";
        const base = col.replace(` (${ds.name})`, "");
        const j = ds.columns.indexOf(base);
        if (j >= 0) return other[j] ?? "";
      }
      return "";
    });
    rows.push(out);
  }

  return { columns: mergedColumns, rows, rowCount: rows.length };
}

export function downloadCsv(filename: string, columns: string[], rows: string[][]) {
  const blob = new Blob([datasetsToCsv(columns, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Pick numeric series from sample rows for quick charts. */
export function numericSeries(
  columns: string[],
  rows: string[][],
  xCol: string,
  yCol: string,
  maxPoints = 500,
): { x: string[]; y: number[] } {
  const xi = columns.indexOf(xCol);
  const yi = columns.indexOf(yCol);
  if (xi < 0 || yi < 0) return { x: [], y: [] };
  const step = Math.max(1, Math.floor(rows.length / maxPoints));
  const x: string[] = [];
  const y: number[] = [];
  for (let i = 0; i < rows.length; i += step) {
    const row = rows[i];
    const n = Number.parseFloat(row[yi]?.replace(/[^\d.-]/g, "") ?? "");
    if (!Number.isFinite(n)) continue;
    x.push(row[xi] ?? String(i));
    y.push(n);
  }
  return { x, y };
}

export function numericColumns(columns: string[], rows: string[][]): string[] {
  if (!rows.length) return [];
  return columns.filter((col) => {
    const i = columns.indexOf(col);
    let hits = 0;
    for (const row of rows.slice(0, 50)) {
      const n = Number.parseFloat(row[i]?.replace(/[^\d.-]/g, "") ?? "");
      if (Number.isFinite(n)) hits += 1;
    }
    return hits >= 3;
  });
}

/** Split CSV vertically after column index (UT3-style). */
export function splitCsvVertical(text: string, splitAfterCol: number): { left: string; right: string } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return { left: "", right: "" };
  const header = splitCsvLine(lines[0]);
  const leftIndices = [0, ...header.map((_, i) => i).filter((i) => i > 0 && i <= splitAfterCol)];
  const rightIndices = [0, ...header.map((_, i) => i).filter((i) => i > splitAfterCol)];

  const project = (line: string, cols: number[]) => {
    const cells = splitCsvLine(line);
    return cols.map((i) => cells[i] ?? "").join(",");
  };

  const left = [project(lines[0], leftIndices), ...lines.slice(1).map((l) => project(l, leftIndices))].join("\n");
  const right = [project(lines[0], rightIndices), ...lines.slice(1).map((l) => project(l, rightIndices))].join("\n");
  return { left, right };
}

/** Split CSV horizontally after N data rows (keeps header in both). */
export function splitCsvHorizontal(text: string, dataRowsInFirst: number): { first: string; second: string } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return { first: "", second: "" };
  const header = lines[0];
  const first = [header, ...lines.slice(1, 1 + dataRowsInFirst)].join("\n");
  const second = [header, ...lines.slice(1 + dataRowsInFirst)].join("\n");
  return { first, second };
}

export type QualityReport = {
  duplicateTimestamps: number;
  warnings: { severity: string; code: string; message: string }[];
  readyToCommit: boolean;
};

/** Client-side data quality scan (mirrors server analyze_quality). */
export function analyzeQualityLocal(columns: string[], rows: string[][]): QualityReport {
  const tsCol = detectTimestampColumn(columns);
  const tsIdx = columns.indexOf(tsCol ?? "");
  const seen = new Set<string>();
  let duplicateTimestamps = 0;
  const warnings: QualityReport["warnings"] = [];
  if (tsIdx >= 0) {
    for (const row of rows) {
      const ts = row[tsIdx] ?? "";
      if (seen.has(ts)) duplicateTimestamps += 1;
      else seen.add(ts);
    }
  }
  for (const [i, col] of columns.entries()) {
    if (i === tsIdx) continue;
    let empty = 0;
    for (const row of rows) {
      if (!(row[i] ?? "").trim()) empty += 1;
    }
    if (rows.length > 0 && empty * 2 > rows.length) {
      warnings.push({
        severity: "info",
        code: "sparse_column",
        message: `${col}: ${Math.round((empty / rows.length) * 100)}% empty`,
      });
    }
  }
  if (duplicateTimestamps > 0) {
    warnings.push({
      severity: "warning",
      code: "duplicate_timestamps",
      message: `${duplicateTimestamps} duplicate timestamp(s) in loaded data`,
    });
  }
  const sampleTs = rows[0]?.[tsIdx] ?? "";
  if (sampleTs.includes("/") && !sampleTs.includes("T") && !sampleTs.includes("+")) {
    warnings.push({
      severity: "info",
      code: "timezone_ambiguous",
      message: "Timestamps appear to be local US-style without explicit timezone",
    });
  }
  return {
    duplicateTimestamps,
    warnings,
    readyToCommit: duplicateTimestamps === 0,
  };
}

export function idsFromFilename(filename: string): { siteId: string; equipId: string; sourceId: string } {
  const base = filename.replace(/^.*[/\\]/, "").replace(/\.csv$/i, "");
  const slug = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const s = slug || "csv-import";
  return { siteId: `site:${s}`, equipId: `equip:${s}`, sourceId: `source:csv:${s}` };
}
