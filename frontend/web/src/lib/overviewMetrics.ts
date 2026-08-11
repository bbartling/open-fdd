import { naturalCompare } from "./naturalSort";

/** SQL-only rollups in the registry — not pandas cookbook rules. */
export const SQL_ROLLUP_RULE_IDS = new Set([
  "FAN-RUNTIME-HOURS",
  "AVG-ZONE-TEMP",
  "ZONE-COMFORT-PCT",
  "FAULT-ELAPSED-HOURS",
]);

export function isWeatherEquipmentId(id: string): boolean {
  const s = id.trim().toLowerCase();
  return s === "weather" || s === "(weather)";
}

export function isWeatherEquipment(e: {
  equipment_id?: string;
  equipment_type?: string;
}): boolean {
  if (isWeatherEquipmentId(String(e.equipment_id ?? ""))) return true;
  return String(e.equipment_type ?? "").trim().toLowerCase() === "weather";
}

/** Cookbook kind is lowercase (`ahu`), not display `AHU`. */
export function cookbookKind(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim();
  if (!s || s === "—") return "—";
  return s.toLowerCase();
}

/**
 * Vibe19 metric timestamps: `YYYY-MM-DD HH:mm` from the CSV/historian
 * string, without converting timezone (do not use local Date getters).
 */
export function formatOverviewTs(raw: string | null | undefined): string {
  if (raw == null) return "—";
  const s = String(raw).trim();
  if (!s) return "—";
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : s;
}

export function spanHoursBetween(
  start: string | null | undefined,
  end: string | null | undefined,
): number | null {
  if (!start || !end) return null;
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null;
  return Math.round(((b - a) / 3_600_000) * 10) / 10;
}

export interface SamplingFrame {
  equipment_id?: string;
  equipment_type?: string;
  sampling?: {
    first_timestamp?: string | null;
    last_timestamp?: string | null;
    row_count?: number;
  };
}

/** Building-wide min/max over equipment frames, excluding weather. */
export function datasetTimeSpan(frames: SamplingFrame[]): {
  start: string | null;
  end: string | null;
  span_hours: number | null;
} {
  let start: string | null = null;
  let end: string | null = null;
  let startMs = Number.POSITIVE_INFINITY;
  let endMs = Number.NEGATIVE_INFINITY;
  for (const f of frames) {
    if (isWeatherEquipment(f)) continue;
    const s = f.sampling?.first_timestamp;
    const e = f.sampling?.last_timestamp;
    if (s) {
      const ms = Date.parse(s);
      if (Number.isFinite(ms) && ms < startMs) {
        startMs = ms;
        start = s;
      }
    }
    if (e) {
      const ms = Date.parse(e);
      if (Number.isFinite(ms) && ms > endMs) {
        endMs = ms;
        end = e;
      }
    }
  }
  return { start, end, span_hours: spanHoursBetween(start, end) };
}

/**
 * Cookbook rule count. Prefer the rules list (minus 4 SQL rollups).
 * Status `63` is the SQL registry (59+4); `59` is already cookbook-sized.
 */
export function cookbookRuleCount(
  rules: Array<{ rule_id?: string }>,
  statusCount?: number | null,
): number {
  if (rules.length > 0) {
    return rules.filter(
      (r) => !SQL_ROLLUP_RULE_IDS.has(String(r.rule_id ?? "")),
    ).length;
  }
  const n = Number(statusCount ?? 0);
  if (!Number.isFinite(n) || n <= 0) return 0;
  if (n >= 63) return n - SQL_ROLLUP_RULE_IDS.size;
  return n;
}

export function inventoryWithoutWeather<
  T extends { equipment_id?: string; equipment_type?: string },
>(items: T[]): T[] {
  return items
    .filter((e) => !isWeatherEquipment(e))
    .sort((a, b) =>
      naturalCompare(String(a.equipment_id ?? ""), String(b.equipment_id ?? "")),
    );
}
