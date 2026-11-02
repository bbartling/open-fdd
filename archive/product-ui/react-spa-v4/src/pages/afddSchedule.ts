export type AfddScheduleKind = "interval" | "wall_clock";

export interface AfddScheduleInput {
  scheduleKind: AfddScheduleKind;
  intervalMinutes: number;
  lookbackDays: number;
  wallClockHhmm: string;
  wallClockTimezone: string;
}

const UNBOUNDED = /^(all|\*|full|history|retained|update_all|rescan)$/i;

/** Scheduler save body. Never includes an update-all flag. */
export function buildAfddSchedulePayload(input: AfddScheduleInput): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    schedule_kind: input.scheduleKind,
    interval_minutes: input.scheduleKind === "wall_clock" ? 1440 : input.intervalMinutes,
    lookback_days: input.lookbackDays,
  };
  if (input.scheduleKind === "wall_clock") {
    const hhmm = input.wallClockHhmm.trim();
    const timezone = input.wallClockTimezone.trim();
    if (!/^\d{2}:\d{2}$/.test(hhmm)) {
      throw new Error("Wall-clock time must be HH:MM");
    }
    if (!timezone || UNBOUNDED.test(timezone)) {
      throw new Error("Wall-clock timezone must be an IANA name");
    }
    payload.wall_clock_hhmm = hhmm;
    payload.wall_clock_timezone = timezone;
  }
  return payload;
}

export interface AfddBackfillInput {
  buildingId?: string;
  startUtc: string;
  endUtc: string;
  chunkHours?: number;
}

/** Explicit historical range. Rejects empty bounds and unbounded tokens. */
export function buildAfddBackfillPayload(input: AfddBackfillInput): Record<string, unknown> {
  const start = input.startUtc.trim();
  const end = input.endUtc.trim();
  if (!start || !end || UNBOUNDED.test(start) || UNBOUNDED.test(end)) {
    throw new Error("Backfill requires an explicit start and end");
  }
  const payload: Record<string, unknown> = {
    start_utc: start,
    end_utc: end,
    chunk_hours: input.chunkHours ?? 24,
  };
  const building = input.buildingId?.trim();
  if (building) payload.building_id = building;
  return payload;
}

/** `datetime-local` values are operator-local. Send UTC RFC3339. */
export function localInputToUtc(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || UNBOUNDED.test(trimmed)) {
    throw new Error("Backfill requires an explicit start and end");
  }
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error("Backfill time is not a valid local timestamp");
  }
  return parsed.toISOString();
}
