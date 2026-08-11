import { describe, expect, it } from "vitest";
import {
  cookbookKind,
  cookbookRuleCount,
  datasetTimeSpan,
  formatOverviewTs,
  inventoryWithoutWeather,
  isWeatherEquipment,
  SQL_ROLLUP_RULE_IDS,
} from "./overviewMetrics";

describe("overviewMetrics", () => {
  it("excludes weather from inventory", () => {
    const items = inventoryWithoutWeather([
      { equipment_id: "weather", equipment_type: "weather" },
      { equipment_id: "AHU_10", equipment_type: "AHU" },
      { equipment_id: "AHU_2", equipment_type: "AHU" },
    ]);
    expect(items.map((e) => e.equipment_id)).toEqual(["AHU_2", "AHU_10"]);
    expect(isWeatherEquipment({ equipment_id: "weather" })).toBe(true);
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
        equipment_id: "weather",
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
