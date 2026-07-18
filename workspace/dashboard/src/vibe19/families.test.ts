import { describe, expect, it } from "vitest";
import { FAMILY_LABELS, groupRulesByFamily, ruleFamily } from "./families";

describe("ruleFamily", () => {
  it("matches the vibe19 cookbook catalog families", () => {
    expect(ruleFamily("FC1")).toBe("ahu");
    expect(ruleFamily("ECON-3")).toBe("ahu");
    expect(ruleFamily("OAT-METEO")).toBe("ahu");
    expect(ruleFamily("SV-RATE")).toBe("sensor");
    expect(ruleFamily("SV-SLEW")).toBe("sensor");
    expect(ruleFamily("PID-HUNT-1")).toBe("control");
    expect(ruleFamily("VAV-REHEAT")).toBe("vav");
    expect(ruleFamily("CHW-2")).toBe("plant");
    expect(ruleFamily("CW-FAN-1")).toBe("plant");
    expect(ruleFamily("HP-1")).toBe("heatpump");
    expect(ruleFamily("WX-1")).toBe("weather");
    expect(ruleFamily("TRIM-3")).toBe("trim");
    expect(ruleFamily("SCHED-247")).toBe("schedule");
    expect(ruleFamily("MYSTERY-9")).toBe("other");
  });
});

describe("groupRulesByFamily", () => {
  it("orders buckets by family and uses numbered vibe19 labels", () => {
    const grouped = groupRulesByFamily(["CHW-1", "FC1", "SV-RANGE", "SCHED-1"]);
    expect(grouped.map(([label]) => label)).toEqual([
      FAMILY_LABELS.sensor,
      FAMILY_LABELS.ahu,
      FAMILY_LABELS.plant,
      FAMILY_LABELS.schedule,
    ]);
    expect(grouped[0][1]).toEqual(["SV-RANGE"]);
  });
});
