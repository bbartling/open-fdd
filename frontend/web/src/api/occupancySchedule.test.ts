import { describe, expect, it } from "vitest";
import {
  defaultOccupancyWeek,
  occupiedHoursPerWeek,
  scheduleReferenceClause,
  scheduleReferenceFromSession,
  weekBucketIsComplete,
  weekBucketIsPartial,
} from "./occupancySchedule";

describe("occupancy schedule reference", () => {
  it("defaults to a 50 hour Monday–Friday calendar", () => {
    const schedule = scheduleReferenceFromSession(null, "UTC");
    expect(schedule.hours).toBe(50);
    expect(schedule.source).toBe("default");
    expect(scheduleReferenceClause(schedule)).toBe("schedule 50 h/week (default)");
  });

  it("uses the saved calendar instead of a stale nominal hour field", () => {
    const schedule = scheduleReferenceFromSession(
      {
        schema_version: "openfdd.session.v1",
        occupancy_schedule: {
          timezone: "America/Chicago",
          nominal_occ_hours_week: 60,
          days: {
            mon: { occupied: true, start: "07:00", end: "17:00" },
            tue: { occupied: true, start: "07:00", end: "17:00" },
            wed: { occupied: true, start: "07:00", end: "17:00" },
            thu: { occupied: true, start: "07:00", end: "17:00" },
            fri: { occupied: false, start: "07:00", end: "17:00" },
            sat: { occupied: false, start: "07:00", end: "17:00" },
            sun: { occupied: false, start: "07:00", end: "17:00" },
          },
        },
      },
      "UTC",
    );
    expect(schedule.hours).toBe(40);
    expect(schedule.timezone).toBe("America/Chicago");
    expect(schedule.source).toBe("session");
    expect(scheduleReferenceClause(schedule)).toBe(
      "schedule 40 h/week (America/Chicago, session openfdd.session.v1)",
    );
  });

  it("keeps a 07:00–17:00 block at 10 wall-clock hours", () => {
    const week = defaultOccupancyWeek();
    week.Sunday = { occupied: true, start: "07:00", end: "17:00" };
    expect(occupiedHoursPerWeek(week)).toBe(60);
    expect(occupiedHoursPerWeek(defaultOccupancyWeek())).toBe(50);
  });

  it("does not read a global occupancy draft from browser storage", () => {
    localStorage.setItem(
      "openfdd.ui.occupancy_schedule.v2",
      JSON.stringify({
        tz: "Pacific/Honolulu",
        week: {
          Monday: { occupied: true, start: "00:00", end: "24:00" },
          Tuesday: { occupied: true, start: "00:00", end: "24:00" },
          Wednesday: { occupied: true, start: "00:00", end: "24:00" },
          Thursday: { occupied: true, start: "00:00", end: "24:00" },
          Friday: { occupied: true, start: "00:00", end: "24:00" },
          Saturday: { occupied: true, start: "00:00", end: "24:00" },
          Sunday: { occupied: true, start: "00:00", end: "24:00" },
        },
      }),
    );
    const schedule = scheduleReferenceFromSession(undefined, "UTC");
    expect(schedule.hours).toBe(50);
    expect(schedule.timezone).toBe("UTC");
    expect(schedule.source).toBe("default");
    localStorage.removeItem("openfdd.ui.occupancy_schedule.v2");
  });

  it("marks a window-clipped week partial and a covered week complete", () => {
    const full = {
      week_start: "2026-06-01T00:00:00Z",
      partial_week: false,
    };
    const clipped = {
      week_start: "2026-06-08T00:00:00Z",
      partial_week: false,
    };
    expect(
      weekBucketIsPartial(full, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z"),
    ).toBe(false);
    expect(
      weekBucketIsPartial(clipped, "2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z"),
    ).toBe(true);
    expect(
      weekBucketIsPartial(
        { week_start: "2026-06-01T00:00:00Z", partial_week: true },
        "2026-05-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
      ),
    ).toBe(true);
  });

  it("does not treat a short historian span as a full week", () => {
    // 2016 five-minute samples ≈ one full week. A span under six days
    // (6 * 24 * 12 = 1728 samples at 5 min) must stay partial.
    const fullWeekSamples = 2016;
    const shortWeekSamples = 1008; // 3.5 days at 5-minute cadence
    expect(fullWeekSamples).toBe(7 * 24 * 12);
    expect(shortWeekSamples).toBeLessThan(6 * 24 * 12);
    const shortSpan = {
      week_start: "2026-06-01T00:00:00Z",
      partial_week: true,
      n_observations: shortWeekSamples,
    };
    const sixDayComplete = {
      week_start: "2026-06-01T00:00:00Z",
      partial_week: false,
      n_observations: fullWeekSamples,
    };
    expect(
      weekBucketIsPartial(shortSpan, "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    ).toBe(true);
    expect(
      weekBucketIsComplete(shortSpan, "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    ).toBe(false);
    expect(
      weekBucketIsComplete(
        sixDayComplete,
        "2026-05-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
      ),
    ).toBe(true);
    expect(
      weekBucketIsComplete(
        sixDayComplete,
        "2026-06-01T00:00:00Z",
        "2026-06-05T00:00:00Z",
      ),
    ).toBe(false);
  });
});
