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

  it("puts device name in title and short description as symptom", () => {
    const families: FaultFamily[] = [
      {
        family: "FDD:demo",
        label: "BACnet MS/TP device 5007",
        worst: "warning",
        traffic: "yellow",
        count: 1,
        faults: [
          {
            id: "fdd-1",
            severity: "warning",
            title: "BACnet MS/TP device 5007 — humidity out of bounds (24 samples) at demo",
            source: "fdd",
            equipment_name: "BACnet MS/TP device 5007",
            short_description: "Humidity reading is outside the configured range.",
            data_source: "BACnet · 5007",
            model_context: {
              equipment: { id: "bacnet-5007", name: "BACnet MS/TP device 5007", type: "BACnet_Device" },
              short_description: "Humidity reading is outside the configured range.",
              data_source: "BACnet · 5007",
            },
          },
        ],
      },
    ];
    const cards = buildDisplayFaults(families);
    expect(cards[0]?.title).toBe("BACnet MS/TP device 5007");
    expect(cards[0]?.symptom).toBe("Humidity reading is outside the configured range.");
    expect(cards[0]?.dataSource).toBe("BACnet · 5007");
  });
});
