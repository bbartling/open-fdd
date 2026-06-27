import { describe, expect, it } from "vitest";
import { buildDisplayFaults } from "./displayFaults";
import type { FaultFamily } from "./dashboardStream";

describe("buildDisplayFaults", () => {
  it("groups historian lag alerts into one card", () => {
    const families: FaultFamily[] = [
      {
        family: "POLL:v1",
        label: "Jci Vav 10",
        worst: "warning",
        traffic: "yellow",
        count: 1,
        faults: [
          {
            id: "a1",
            severity: "warning",
            title: "Jci Vav 10: historian behind live poll",
            source: "poll_health",
            equipment_name: "Jci Vav 10",
          },
        ],
      },
      {
        family: "POLL:v2",
        label: "Jci Vav 11",
        worst: "warning",
        traffic: "yellow",
        count: 1,
        faults: [
          {
            id: "a2",
            severity: "warning",
            title: "Jci Vav 11: historian behind live poll",
            source: "poll_health",
            equipment_name: "Jci Vav 11",
          },
        ],
      },
    ];
    const cards = buildDisplayFaults(families);
    const group = cards.find((c) => c.id === "group-historian-lag");
    expect(group).toBeDefined();
    expect(group?.underlying.length).toBe(2);
    expect(cards.filter((c) => c.source === "poll_health").length).toBe(1);
  });

  it("includes fault analytics meta when present", () => {
    const families: FaultFamily[] = [
      {
        family: "oa_temp_out_of_range",
        label: "equip:local-test-equipment",
        worst: "warning",
        traffic: "yellow",
        count: 1,
        faults: [
          {
            id: "fault-oa-1",
            severity: "warning",
            title: "OA Temperature Out Of Range",
            detail: "equip:local-test-equipment",
            source: "fdd_rule",
            analytics: {
              first_seen_at: "2026-06-21T10:00:00Z",
              last_seen_at: "2026-06-21T12:00:00Z",
              estimated_fault_duration_label: "2.0 h",
              avg_value_fault: 115,
              avg_value_normal: 72,
              fault_samples: 8,
              total_samples: 24,
              value_unit: "°F",
            },
          },
        ],
      },
    ];
    const cards = buildDisplayFaults(families);
    const card = cards[0];
    expect(card.meta.some((m) => m.label === "Time in fault" && m.value.includes("2.0"))).toBe(true);
    expect(card.meta.some((m) => m.label === "First seen")).toBe(true);
    expect(card.meta.some((m) => m.label === "Avg in fault")).toBe(true);
  });
});
