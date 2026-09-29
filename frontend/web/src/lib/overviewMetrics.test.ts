import { describe, expect, it } from "vitest";
import {
  cookbookKind,
  cookbookRuleCount,
  datasetTimeSpan,
  analyticsWindowFromSampling,
  ANALYTICS_WINDOW_MAX_DAYS,
  formatOverviewTs,
  inventoryWithoutWeather,
  isWeatherEquipment,
  isZoneTerminalEquipment,
  pickWeatherFaultRow,
  SQL_ROLLUP_RULE_IDS,
} from "./overviewMetrics";

describe("overviewMetrics", () => {
  it("excludes weather from inventory", () => {
    const items = inventoryWithoutWeather([
      { equipment_id: "OA_REF", equipment_type: "WEATHER" },
      { equipment_id: "AHU_10", equipment_type: "AHU" },
      { equipment_id: "AHU_2", equipment_type: "AHU" },
      { equipment_id: "weather_station", equipment_type: "AHU" },
    ]);
    expect(items.map((e) => e.equipment_id)).toEqual([
      "AHU_2",
      "AHU_10",
      "weather_station",
    ]);
    expect(isWeatherEquipment({ equipment_id: "weather" })).toBe(false);
    expect(isWeatherEquipment({ equipment_type: "weather" })).toBe(true);
    expect(
      isWeatherEquipment({ equipment_id: "jci_met", equipment_type_raw: "weather" }),
    ).toBe(true);
  });

  it("treats zone membership as a stamp, not an id substring", () => {
    expect(isZoneTerminalEquipment({ equipment_id: "AHU-1-VAV-03" })).toBe(
      false,
    );
    expect(
      isZoneTerminalEquipment({
        equipment_id: "AHU-1-VAV-03",
        equipment_type: "AHU",
      }),
    ).toBe(false);
    expect(isZoneTerminalEquipment({ equipment_type: "VAV" })).toBe(true);
    expect(
      isZoneTerminalEquipment({
        equipment_id: "jci_vav_1",
        equipment_type_raw: "vav",
      }),
    ).toBe(true);
    expect(
      isZoneTerminalEquipment({ equipment_id: "bldg2-zone-loopback" }),
    ).toBe(false);
    expect(isZoneTerminalEquipment({ equipment_type: "FCU" })).toBe(true);
  });

  it("picks the OAT-METEO row by weather kind", () => {
    const row = pickWeatherFaultRow(
      [
        { equipment_id: "AHU_WEATHER", equipment_type: "AHU", fault_hours: 9 },
        { equipment_id: "OA_REF", equipment_type: "WEATHER", fault_hours: 1 },
      ],
      new Set(["OA_REF"]),
    );
    expect(row?.equipment_id).toBe("OA_REF");
    expect(
      pickWeatherFaultRow(
        [{ equipment_id: "weather_station", fault_hours: 4 }],
        new Set(),
      ),
    ).toBeUndefined();
  });

  it("formats timestamps like vibe19 and lowercases kind", () => {
    expect(formatOverviewTs("2026-03-16T00:40:00")).toBe("2026-03-16 00:40");
    expect(formatOverviewTs("2026-07-17T10:00:00")).toBe("2026-07-17 10:00");
    expect(cookbookKind("AHU")).toBe("ahu");
  });

  it("computes building-wide span excluding weather", () => {
    const span = datasetTimeSpan([
      {
        equipment_id: "AHU_1",
        sampling: {
          first_timestamp: "2026-03-16T00:40:00",
          last_timestamp: "2026-07-17T10:00:00",
        },
      },
      {
        equipment_id: "OA_REF",
        equipment_type: "WEATHER",
        sampling: {
          first_timestamp: "2020-01-01T00:00:00",
          last_timestamp: "2029-12-31T00:00:00",
        },
      },
    ]);
    expect(formatOverviewTs(span.start)).toBe("2026-03-16 00:40");
    expect(formatOverviewTs(span.end)).toBe("2026-07-17 10:00");
    expect(span.span_hours).toBe(2961.3);
  });

  it("builds analytics window from package sampling (not wall-clock)", () => {
    const frames = [
      {
        equipment_id: "AHU_1",
        sampling: {
          first_timestamp: "2026-03-16T00:40:00",
          last_timestamp: "2026-07-17T10:00:00",
        },
      },
    ];
    const w = analyticsWindowFromSampling(frames);
    expect(w.start).toBeTruthy();
    expect(w.end).toBeTruthy();
    expect(Date.parse(w.start!)).toBe(Date.parse("2026-03-16T00:40:00"));
    // end is last sample + 1h pad
    expect(Date.parse(w.end!)).toBe(
      Date.parse("2026-07-17T10:00:00") + 3_600_000,
    );
    expect(analyticsWindowFromSampling([])).toEqual({});
  });

  it("caps long dataset spans to ANALYTICS_WINDOW_MAX_DAYS from end", () => {
    const frames = [
      {
        equipment_id: "AHU_1",
        sampling: {
          first_timestamp: "2024-01-01T00:00:00Z",
          last_timestamp: "2026-07-01T00:00:00Z",
        },
      },
    ];
    const w = analyticsWindowFromSampling(frames);
    const spanDays =
      (Date.parse(w.end!) - Date.parse(w.start!)) / 86_400_000;
    expect(spanDays).toBeLessThanOrEqual(ANALYTICS_WINDOW_MAX_DAYS + 1 / 24 + 0.01);
    expect(Date.parse(w.start!)).toBeGreaterThan(Date.parse("2024-01-01T00:00:00Z"));
  });

  it("counts 59 cookbook rules and leaves 4 SQL rollups out", () => {
    const rules = [
      ...Array.from({ length: 59 }, (_, i) => ({ rule_id: `RULE-${i}` })),
      ...[...SQL_ROLLUP_RULE_IDS].map((rule_id) => ({ rule_id })),
    ];
    expect(cookbookRuleCount(rules, 63)).toBe(59);
    expect(cookbookRuleCount([], 63)).toBe(59);
    expect(cookbookRuleCount([], 59)).toBe(59);
    expect(cookbookRuleCount([], 1)).toBe(1);
  });
});
