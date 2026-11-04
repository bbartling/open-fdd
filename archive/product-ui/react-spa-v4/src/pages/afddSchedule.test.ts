import { describe, expect, it } from "vitest";
import {
  buildAfddBackfillPayload,
  buildAfddSchedulePayload,
  localInputToUtc,
} from "./afddSchedule";

describe("AFDD schedule payloads", () => {
  it("saves a daily wall-clock slot without an update-all flag", () => {
    const payload = buildAfddSchedulePayload({
      scheduleKind: "wall_clock",
      intervalMinutes: 60,
      lookbackDays: 1,
      wallClockHhmm: "05:00",
      wallClockTimezone: "America/Chicago",
    });
    expect(payload).toEqual({
      schedule_kind: "wall_clock",
      interval_minutes: 1440,
      lookback_days: 1,
      wall_clock_hhmm: "05:00",
      wall_clock_timezone: "America/Chicago",
    });
    expect(payload).not.toHaveProperty("update_all");
    expect(payload).not.toHaveProperty("rescan_all");
  });

  it("rejects an unbounded timezone token", () => {
    expect(() =>
      buildAfddSchedulePayload({
        scheduleKind: "wall_clock",
        intervalMinutes: 1440,
        lookbackDays: 1,
        wallClockHhmm: "05:00",
        wallClockTimezone: "all",
      }),
    ).toThrow(/IANA/);
  });

  it("keeps interval cadence when wall clock is off", () => {
    const payload = buildAfddSchedulePayload({
      scheduleKind: "interval",
      intervalMinutes: 180,
      lookbackDays: 2,
      wallClockHhmm: "05:00",
      wallClockTimezone: "America/Chicago",
    });
    expect(payload.schedule_kind).toBe("interval");
    expect(payload.interval_minutes).toBe(180);
    expect(payload).not.toHaveProperty("wall_clock_hhmm");
  });
});

describe("AFDD bounded backfill payloads", () => {
  it("requires an explicit range", () => {
    expect(() =>
      buildAfddBackfillPayload({ startUtc: "all", endUtc: "2026-09-29T00:00:00Z" }),
    ).toThrow(/explicit start and end/);
    expect(() => buildAfddBackfillPayload({ startUtc: "", endUtc: "" })).toThrow(
      /explicit start and end/,
    );
  });

  it("sends only the chosen window", () => {
    const payload = buildAfddBackfillPayload({
      startUtc: "2026-09-27T00:00:00Z",
      endUtc: "2026-09-29T00:00:00Z",
      chunkHours: 24,
    });
    expect(payload).toEqual({
      start_utc: "2026-09-27T00:00:00Z",
      end_utc: "2026-09-29T00:00:00Z",
      chunk_hours: 24,
    });
    expect(payload).not.toHaveProperty("update_all");
  });

  it("converts a local datetime input to UTC", () => {
    const utc = localInputToUtc("2026-09-29T05:00");
    expect(utc).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(() => localInputToUtc("all")).toThrow(/explicit/);
  });
});
