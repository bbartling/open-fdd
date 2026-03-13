import { apiFetchBlob, apiFetchText } from "@/lib/api";

export interface CsvRequest {
  site_id: string;
  start_date: string;
  end_date: string;
  format?: "wide" | "long";
  point_ids?: string[];
}

export interface LongCsvRow {
  timestamp: number;
  pointKey: string;
  value: number;
}

export interface PivotRow {
  timestamp: number;
  [key: string]: number;
}

function parseCsvLine(line: string): string[] {
  const out: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      out.push(current);
      current = "";
    } else {
      current += ch;
    }
  }

  out.push(current);
  return out;
}

export async function fetchCsv(body: CsvRequest): Promise<string> {
  return apiFetchText("/download/csv", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/csv" },
    body: JSON.stringify({ ...body, format: body.format ?? "wide" }),
  });
}

export function parseLongCsv(csv: string): LongCsvRow[] {
  const normalized = csv.replace(/^\uFEFF/, "").trim();
  if (!normalized) return [];

  const lines = normalized.split(/\r?\n/).filter(Boolean);
  if (lines.length <= 1) return [];

  const headers = parseCsvLine(lines[0]).map((header) => header.trim().toLowerCase());
  const tsIndex = headers.findIndex((h) => h === "ts" || h === "timestamp" || h === "time");
  const keyIndex = headers.findIndex(
    (h) => h === "point_key" || h === "point_id" || h === "external_id" || h === "point",
  );
  const valueIndex = headers.findIndex((h) => h === "value");

  if (tsIndex < 0 || keyIndex < 0 || valueIndex < 0) return [];

  return lines
    .slice(1)
    .map((line) => parseCsvLine(line))
    .map((cols) => {
      const date = new Date(cols[tsIndex] ?? "");
      const value = Number(cols[valueIndex]);
      return {
        timestamp: date.getTime(),
        pointKey: cols[keyIndex] ?? "",
        value,
      };
    })
    .filter((row) => Number.isFinite(row.timestamp) && row.pointKey && Number.isFinite(row.value));
}

export function pivotForChart(rows: LongCsvRow[]): PivotRow[] {
  const byTimestamp = new Map<number, PivotRow>();

  for (const row of rows) {
    const existing = byTimestamp.get(row.timestamp) ?? { timestamp: row.timestamp };
    existing[row.pointKey] = row.value;
    byTimestamp.set(row.timestamp, existing);
  }

  return Array.from(byTimestamp.values()).sort((a, b) => a.timestamp - b.timestamp);
}

export async function downloadTimeseriesCsv(body: CsvRequest, filename: string): Promise<void> {
  const blob = await apiFetchBlob("/download/csv", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/csv" },
    body: JSON.stringify({ ...body, format: body.format ?? "wide" }),
  });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}