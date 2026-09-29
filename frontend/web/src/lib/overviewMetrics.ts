import { naturalCompare } from "./naturalSort";

/** SQL-only rollups in the registry — not pandas cookbook rules. */
export const SQL_ROLLUP_RULE_IDS = new Set([
  "FAN-RUNTIME-HOURS",
  "AVG-ZONE-TEMP",
  "ZONE-COMFORT-PCT",
  "FAULT-ELAPSED-HOURS",
]);

/** Canonical product kind from a stamp or display label. Id text is ignored. */
export function canonicalEquipmentKind(
  raw: string | null | undefined,
): string | null {
  const key = String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
  switch (key) {
    case "ahu":
    case "airhandler":
    case "airhandlingunit":
    case "rtu":
    case "mau":
    case "doas":
    case "cvahu":
    case "vavahu":
    case "unitventilator":
    case "uv":
    case "erv":
    case "energyrecoveryventilator":
      return "ahu";
    case "vav":
    case "vavbox":
    case "zoneterminal":
      return "vav";
    case "zoneother":
    case "zone":
    case "fcu":
    case "fancoil":
    case "fancoilunit":
    case "standaloneddc":
    case "ddczone":
    case "zoneddc":
      return "zone_other";
    case "chiller":
    case "chwplant":
    case "chilledwaterplant":
      return "chiller";
    case "coolingtower":
    case "tower":
      return "cooling_tower";
    case "boiler":
    case "hwplant":
    case "hotwaterplant":
      return "boiler";
    case "heatpump":
    case "hp":
      return "heatpump";
    case "weather":
      return "weather";
    case "meter":
    case "electricmeter":
    case "utilitymeter":
    case "powermeter":
      return "meter";
    case "vrf":
      return "vrf";
    default:
      return null;
  }
}

export function equipmentKind(e: {
  equipment_id?: unknown;
  equipment_type?: unknown;
  equipment_type_raw?: unknown;
  equipType?: unknown;
}): string | null {
  const raw = e.equipment_type_raw ?? e.equipType;
  const fromRaw = canonicalEquipmentKind(raw == null ? "" : String(raw));
  if (fromRaw) return fromRaw;
  return canonicalEquipmentKind(
    e.equipment_type == null ? "" : String(e.equipment_type),
  );
}

/** Zone terminals and zone-other controls stay out of plant motor groups. */
export function isZoneTerminalEquipment(e: {
  equipment_id?: unknown;
  equipment_type?: unknown;
  equipment_type_raw?: unknown;
  equipType?: unknown;
  label?: unknown;
}): boolean {
  const kind = equipmentKind(e);
  return kind === "vav" || kind === "zone_other";
}

export function isWeatherEquipment(e: {
  equipment_id?: unknown;
  equipment_type?: unknown;
  equipment_type_raw?: unknown;
  equipType?: unknown;
}): boolean {
  return equipmentKind(e) === "weather";
}

/** OAT-METEO row for weather equipment. Id substrings do not qualify. */
export function pickWeatherFaultRow<
  T extends {
    equipment_id?: unknown;
    equipment_type?: unknown;
    equipment_type_raw?: unknown;
    equipType?: unknown;
  },
>(rows: T[], weatherIds: ReadonlySet<string>): T | undefined {
  return rows.find((r) => {
    const id = String(r.equipment_id ?? "");
    if (id && weatherIds.has(id)) return true;
    return isWeatherEquipment(r);
  });
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
 * Historian analytics window for Overview / RCx.
 *
 * Prefer the package sampling span (CSV / import jobs), not wall-clock "last
 * 30 days". Wall-clock windows miss historical packages that are not the
 * current month and skip central's empty-window retain fallback because `start` is set.
 *
 * Cap to the last {@link ANALYTICS_WINDOW_MAX_DAYS} of the dataset so large
 * multi-month historians stay within Railway query budgets.
 *
 * When sampling is missing, omit start/end so central defaults + retain floor apply.
 */
export const ANALYTICS_WINDOW_MAX_DAYS = 180;

export function analyticsWindowFromSampling(frames: SamplingFrame[]): {
  start?: string;
  end?: string;
} {
  const span = datasetTimeSpan(frames);
  if (!span.end) return {};
  const endMs = Date.parse(span.end);
  if (!Number.isFinite(endMs)) return {};
  const maxMs = ANALYTICS_WINDOW_MAX_DAYS * 86_400_000;
  let fromMs = span.start ? Date.parse(span.start) : endMs - maxMs;
  if (!Number.isFinite(fromMs)) fromMs = endMs - maxMs;
  if (endMs - fromMs > maxMs) fromMs = endMs - maxMs;
  // Inclusive end pad so the last sample interval is not clipped.
  const endPadMs = Math.min(endMs + 3_600_000, endMs + maxMs);
  return {
    start: new Date(fromMs).toISOString(),
    end: new Date(endPadMs).toISOString(),
  };
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
