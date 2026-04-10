import { describe, it, expect } from "vitest";
import { PREDEFINED_QUERIES } from "@/data/data-model-testing-queries";

/** AVAILABLE_COMPONENTS from brick_model_summarizer — predefined tests should cover these. */
const AVAILABLE_COMPONENT_IDS = [
  "class_tag_summary",
  "ahu_information",
  "zone_information",
  "building_information",
  "meter_information",
  "central_plant_information",
  "number_of_vav_boxes_per_ahu",
] as const;

describe("DataModelTestingPage PREDEFINED_QUERIES", () => {
  it("includes an entry for each AVAILABLE_COMPONENTS id", () => {
    const ids = new Set(PREDEFINED_QUERIES.map((q) => q.id));
    for (const id of AVAILABLE_COMPONENT_IDS) {
      expect(ids.has(id), `missing predefined query: ${id}`).toBe(true);
    }
  });

  it("each query has id, shortLabel, label, and valid SPARQL (PREFIX and SELECT)", () => {
    for (const q of PREDEFINED_QUERIES) {
      expect(q.id).toBeTruthy();
      expect(q.shortLabel).toBeTruthy();
      expect(q.label).toBeTruthy();
      expect(q.query).toContain("PREFIX");
      expect(q.query).toContain("SELECT");
    }
  });

  it("has no duplicate ids", () => {
    const ids = PREDEFINED_QUERIES.map((q) => q.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("all queries use Brick namespace", () => {
    const brickNs = "https://brickschema.org/schema/Brick#";
    for (const q of PREDEFINED_QUERIES) {
      if ((q.category ?? "hvac") === "hvac") {
        expect(q.query).toContain(brickNs);
      }
    }
  });

  it("engineering category queries exist", () => {
    const engineeringCount = PREDEFINED_QUERIES.filter(
      (q) => (q.category ?? "hvac") === "engineering",
    ).length;
    expect(engineeringCount).toBeGreaterThan(0);
  });

  it("when queryWithBacnet is present it selects BACnet refs (ofdd)", () => {
    for (const q of PREDEFINED_QUERIES) {
      if (q.queryWithBacnet) {
        expect(q.queryWithBacnet).toContain("ofdd:");
        expect(q.queryWithBacnet).toContain("object_identifier");
        expect(q.queryWithBacnet).toContain("SELECT");
      }
    }
  });
});
