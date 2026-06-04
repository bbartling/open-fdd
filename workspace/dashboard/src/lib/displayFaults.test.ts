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
});
