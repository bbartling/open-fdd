import Papa from "papaparse";

export type CsvCell = string | number | boolean | null;

export interface ParsedCsv {
  headers: string[];
  rows: Record<string, CsvCell>[];
}

export interface FaultPoint {
  time: string;
  metric: string;
  value: number;
}

function toNum(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function toTsMs(v: unknown): number | null {
  if (v instanceof Date) {
    const t = v.getTime();
    return Number.isFinite(t) ? t : null;
  }
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v !== "string" || v.trim() === "") return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : null;
}

export function parseCsvText(text: string): ParsedCsv {
  const out = Papa.parse<Record<string, CsvCell>>(text, {
    header: true,
    dynamicTyping: true,
    skipEmptyLines: true,
  });
  const rows = (out.data ?? []).filter((row: Record<string, CsvCell>) => Object.keys(row).length > 0);
  const headers = (out.meta.fields ?? [])
    .map((h: string) => String(h).trim())
    .filter(Boolean);
  return { headers, rows };
}

export function inferXColumn(headers: string[]): string | null {
  const preferred = ["timestamp", "ts", "time", "datetime", "date"];
  const normalized = headers.map((h) => ({ raw: h, norm: h.toLowerCase() }));
  for (const p of preferred) {
    const hit = normalized.find((h) => h.norm === p);
    if (hit) return hit.raw;
  }
  for (const p of preferred) {
    const hit = normalized.find((h) => h.norm.includes(p));
    if (hit) return hit.raw;
  }
  return headers.length > 0 ? headers[0] : null;
}

export function inferYColumns(parsed: ParsedCsv, xCol: string | null): string[] {
  if (parsed.headers.length === 0) return [];
  const out: string[] = [];
  for (const h of parsed.headers) {
    if (xCol && h === xCol) continue;
    let numericCount = 0;
    let seen = 0;
    for (const row of parsed.rows.slice(0, 400)) {
      const v = row[h];
      if (v == null || v === "") continue;
      seen += 1;
      if (toNum(v) != null) numericCount += 1;
    }
    if (seen > 0 && numericCount / seen >= 0.6) out.push(h);
  }
  return out.slice(0, 8);
}

export type JoinedFaultMode = "hour" | "day";

export function pickFaultBucket(startIso: string, endIso: string): JoinedFaultMode {
  const span = Date.parse(endIso) - Date.parse(startIso);
  if (!Number.isFinite(span)) return "day";
  return span <= 2 * 24 * 60 * 60 * 1000 ? "hour" : "day";
}

export function joinFaultSignals(
  csv: ParsedCsv,
  xColumn: string,
  faults: FaultPoint[],
  bucket: JoinedFaultMode,
): ParsedCsv {
  const bucketMs = bucket === "hour" ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
  const metrics = Array.from(new Set(faults.map((f) => f.metric).filter(Boolean)));
  if (metrics.length === 0) return csv;

  const activeByMetric = new Map<string, Array<{ start: number; end: number }>>();
  for (const metric of metrics) activeByMetric.set(metric, []);
  for (const f of faults) {
    if (!f.metric || f.value <= 0) continue;
    const start = Date.parse(f.time);
    if (!Number.isFinite(start)) continue;
    activeByMetric.get(f.metric)?.push({ start, end: start + bucketMs });
  }

  const appended = metrics.map((m) => `fault_${m}`);
  const rows = csv.rows.map((row) => {
    const ts = toTsMs(row[xColumn]);
    const next: Record<string, CsvCell> = { ...row };
    for (const metric of metrics) {
      const active = (activeByMetric.get(metric) ?? []).some(
        (w) => ts != null && ts >= w.start && ts < w.end,
      );
      next[`fault_${metric}`] = active ? 1 : 0;
    }
    return next;
  });
  return { headers: [...csv.headers, ...appended], rows };
}

export function toCsvText(parsed: ParsedCsv): string {
  return Papa.unparse(parsed.rows, { columns: parsed.headers, newline: "\n" });
}

