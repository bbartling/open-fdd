/**
 * Site occupancy calendar shared by Overview and the weekly runtime chart.
 *
 * Occupied hours are wall-clock intervals in the schedule timezone. A daylight-saving
 * transition changes the elapsed length of a civil week and does not change a
 * 07:00–17:00 block. The chart reference is this calendar, read from the site
 * session config. A missing calendar is the default Monday–Friday 07:00–17:00
 * schedule (50 h), not a separate benchmark.
 */

export const DAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export type DayName = (typeof DAY_NAMES)[number];

export type DaySched = { occupied: boolean; start: string; end: string };

export type ScheduleSource = "session" | "default";

export interface ScheduleReference {
  hours: number;
  timezone: string;
  source: ScheduleSource;
  schemaVersion: string;
  week: Record<DayName, DaySched>;
}

const DAY_FROM_KEY: Record<string, DayName> = {
  mon: "Monday",
  monday: "Monday",
  tue: "Tuesday",
  tuesday: "Tuesday",
  wed: "Wednesday",
  wednesday: "Wednesday",
  thu: "Thursday",
  thursday: "Thursday",
  fri: "Friday",
  friday: "Friday",
  sat: "Saturday",
  saturday: "Saturday",
  sun: "Sunday",
  sunday: "Sunday",
};

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export function defaultOccupancyWeek(): Record<DayName, DaySched> {
  const occupied = (day: DayName): DaySched => ({
    occupied: day !== "Saturday" && day !== "Sunday",
    start: "07:00",
    end: "17:00",
  });
  return {
    Monday: occupied("Monday"),
    Tuesday: occupied("Tuesday"),
    Wednesday: occupied("Wednesday"),
    Thursday: occupied("Thursday"),
    Friday: occupied("Friday"),
    Saturday: occupied("Saturday"),
    Sunday: occupied("Sunday"),
  };
}

function clockHours(start: string, end: string): number {
  const parsed = (value: string): number | null => {
    const [hour, minute] = value.split(":");
    const hh = Number(hour);
    const mm = Number(minute);
    if (!Number.isFinite(hh) || !Number.isFinite(mm)) return null;
    return hh + mm / 60;
  };
  const from = parsed(start);
  const to = parsed(end);
  if (from == null || to == null) return 0;
  return Math.max(0, to - from);
}

/** Wall-clock occupied hours for one week. DST does not resize a clock block. */
export function occupiedHoursPerWeek(week: Record<string, DaySched>): number {
  let hours = 0;
  for (const day of DAY_NAMES) {
    const slot = week[day];
    if (!slot?.occupied) continue;
    hours += clockHours(slot.start, slot.end);
  }
  return Math.round(hours * 10) / 10;
}

type SessionSchedule = {
  schema_version?: string;
  occupancy_schedule?: {
    timezone?: string;
    days?: Record<string, { occupied?: boolean; start?: string; end?: string }>;
  };
};

/**
 * Calendar from the site session config. Does not read browser storage, so one
 * site's draft cannot become another site's reference.
 */
export function scheduleReferenceFromSession(
  config: SessionSchedule | null | undefined,
  fallbackTimezone: string,
): ScheduleReference {
  const week = defaultOccupancyWeek();
  const raw = config?.occupancy_schedule;
  const hasSession = raw != null && typeof raw === "object";
  if (hasSession && raw.days && typeof raw.days === "object") {
    for (const [key, slot] of Object.entries(raw.days)) {
      const day = DAY_FROM_KEY[key.trim().toLowerCase()];
      if (!day || !slot || typeof slot !== "object") continue;
      const current = week[day];
      week[day] = {
        occupied: Boolean(slot.occupied),
        start: typeof slot.start === "string" && slot.start.trim() ? slot.start : current.start,
        end: typeof slot.end === "string" && slot.end.trim() ? slot.end : current.end,
      };
    }
  }
  const timezone =
    hasSession && typeof raw.timezone === "string" && raw.timezone.trim()
      ? raw.timezone.trim()
      : fallbackTimezone;
  const schemaVersion =
    typeof config?.schema_version === "string" && config.schema_version.trim()
      ? config.schema_version.trim()
      : "openfdd.session.v1";
  return {
    hours: occupiedHoursPerWeek(week),
    timezone,
    source: hasSession ? "session" : "default",
    schemaVersion,
    week,
  };
}

/** Text shared by the reference line and the runtime provenance string. */
export function scheduleReferenceClause(schedule: ScheduleReference): string {
  if (schedule.source === "session") {
    return `schedule ${schedule.hours} h/week (${schedule.timezone}, session ${schedule.schemaVersion})`;
  }
  return `schedule ${schedule.hours} h/week (default)`;
}

export function formatWeeklyRuntimeProvenance(input: {
  weeklyObservations: number;
  sampleCount: number | null;
  schedule: ScheduleReference | null;
}): string {
  const samples =
    input.sampleCount == null ? "" : ` · samples ${input.sampleCount}`;
  const schedule = input.schedule
    ? ` · ${scheduleReferenceClause(input.schedule)}`
    : "";
  return `POST /api/analytics/runtime (runtime-weekly-v2) · weekly observations ${input.weeklyObservations}${samples}${schedule}`;
}

function parseInstant(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/**
 * A week bucket is partial when the historian says so, or when the requested
 * window does not cover that bucket's Monday-start through the next Monday.
 */
export function weekBucketIsPartial(
  row: Record<string, unknown>,
  windowStart?: string | null,
  windowEnd?: string | null,
): boolean {
  if (row.partial_week === true || row.partial_week === "true") return true;
  const start = parseInstant(row.week_start);
  if (start == null) return false;
  const end = start + WEEK_MS;
  const from = parseInstant(windowStart);
  const to = parseInstant(windowEnd);
  if (from != null && from > start) return true;
  if (to != null && to < end) return true;
  return false;
}

export function partialWeekLabel(label: string, partial: boolean): string {
  if (!partial) return label;
  if (label.endsWith("(partial)")) return label;
  return `${label} (partial)`;
}
