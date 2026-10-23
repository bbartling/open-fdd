import { describe, expect, it } from "vitest";
import { weeklyPlantFigures } from "./centralOverview";
import {
  scheduleReferenceClause,
  scheduleReferenceFromSession,
} from "./occupancySchedule";

const fortyHourSession = {
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
    },
  },
};

function runtimeRows() {
  return [
    {
      kind: "weekly_equipment",
      plant_group: "air",
      equipment_id: "AHU_A",
      label: "AHU_A · fan-status",
      week_label: "2026-W23",
      week_start: "2026-06-01T00:00:00Z",
      run_hours: 40,
      n_observations: 18,
      partial_week: false,
      avg_oat_f: 70,
    },
    {
      kind: "weekly_equipment",
      plant_group: "air",
      equipment_id: "AHU_B",
      label: "AHU_B · fan-status",
      week_label: "2026-W23",
      week_start: "2026-06-01T00:00:00Z",
      run_hours: 12,
      n_observations: 18,
      partial_week: false,
      avg_oat_f: 71,
    },
    {
      kind: "weekly_equipment",
      plant_group: "air",
      equipment_id: "AHU_A",
      label: "AHU_A · fan-status",
      week_label: "2026-W24",
      week_start: "2026-06-08T00:00:00Z",
      run_hours: 3,
      n_observations: 6,
      partial_week: true,
      avg_oat_f: 75,
    },
  ];
}

describe("weekly runtime observation count and schedule reference", () => {
  it("counts weekly cells and draws the session schedule the provenance names", () => {
    const schedule = scheduleReferenceFromSession(fortyHourSession, "UTC");
    const clause = scheduleReferenceClause(schedule);
    const air = weeklyPlantFigures(runtimeRows(), {
      schedule,
      windowStart: "2026-06-01T00:00:00Z",
      windowEnd: "2026-06-15T00:00:00Z",
    }).find((plant) => plant.plant_group === "air");
    const figure = air?.figure;
    expect(figure).toBeTruthy();
    const bars = (figure?.data ?? []).filter((trace) => trace.type === "bar");
    const oat = (figure?.data ?? []).find((trace) => String(trace.name).includes("OAT"));
    const barObservations = bars.reduce((sum, trace) => {
      const ys = Array.isArray(trace.y) ? trace.y : [];
      return sum + ys.filter((value) => value != null).length;
    }, 0);
    expect(barObservations).toBe(3);
    expect(figure?.meta?.weekly_observations).toBe(3);
    expect(figure?.meta?.point_count).toBe(3);
    expect(figure?.meta?.sample_count).toBe(42);
    expect(oat).toBeTruthy();
    expect(figure?.meta?.weekly_observations).not.toBe(
      barObservations + (Array.isArray(oat?.y) ? oat.y.length : 0),
    );
    const shapes = figure?.layout?.shapes as Array<Record<string, unknown>>;
    const annotations = figure?.layout?.annotations as Array<Record<string, unknown>>;
    expect(shapes?.[0]?.y0).toBe(40);
    expect(shapes?.[0]?.y0).toBe(figure?.meta?.schedule_hours);
    expect(annotations?.[0]?.text).toBe(clause);
    expect(figure?.meta?.provenance).toContain(clause);
    expect(figure?.meta?.provenance).toContain("weekly observations 3");
    expect(figure?.meta?.provenance).toContain("samples 42");
    expect(figure?.meta?.provenance).not.toContain("60 h/week");
    const labels = bars[0]?.x ?? [];
    expect(labels).toContain("2026-W23");
    expect(labels).toContain("2026-W24 (partial)");
  });

  it("uses the 50 hour default when the site has no saved calendar", () => {
    const schedule = scheduleReferenceFromSession(null, "UTC");
    const air = weeklyPlantFigures(
      [
        {
          kind: "weekly_equipment",
          plant_group: "air",
          equipment_id: "AHU_A",
          week_label: "2026-W23",
          run_hours: 10,
        },
      ],
      { schedule },
    )[0];
    const shapes = air?.figure?.layout?.shapes as Array<Record<string, unknown>>;
    expect(shapes?.[0]?.y0).toBe(50);
    expect(air?.figure?.meta?.provenance).toContain("schedule 50 h/week (default)");
    expect(air?.figure?.meta?.schedule_hours).toBe(50);
    expect(air?.figure?.meta?.sample_count).toBeUndefined();
  });
});
