import { describe, expect, it } from "vitest";
import { assignmentSummary, parseCommissioningPayload, pointRulePinRows } from "./commissioningImport";

describe("parseCommissioningPayload", () => {
  it("builds point rule pin rows from fdd_rules_linked", () => {
    const payload = parseCommissioningPayload(
      JSON.stringify({
        sites: [],
        equipment: [],
        points: [
          {
            id: "p1",
            description: "OA-T",
            fdd_rule_ids: ["rule-a"],
            fdd_rules_linked: [{ id: "rule-a", name: "Bench OA-T flatline 1h" }],
          },
        ],
        fdd_rules: [{ id: "rule-a", name: "Bench OA-T flatline 1h", bindings: { point_ids: ["p1"] } }],
      }),
    );
    const rows = pointRulePinRows(payload);
    expect(rows).toHaveLength(1);
    expect(rows[0].rules[0].name).toBe("Bench OA-T flatline 1h");
  });

  it("parses commissioning bundle with fdd_rules", () => {
    const payload = parseCommissioningPayload(
      JSON.stringify({
        sites: [{ id: "demo", name: "Demo" }],
        equipment: [],
        points: [{ id: "p1", site_id: "demo", fdd_rule_ids: ["rule-a"] }],
        fdd_rules: [{ id: "rule-a", name: "OOB", bindings: { point_ids: ["p1"] } }],
      }),
    );
    expect(payload.fdd_rules?.[0]?.id).toBe("rule-a");
    expect(payload.points[0].fdd_rule_ids).toEqual(["rule-a"]);
  });

  it("unwraps import_ready_json wrapper", () => {
    const payload = parseCommissioningPayload(
      JSON.stringify({
        import_ready_json: {
          sites: [{ id: "s1", name: "S" }],
          equipment: [],
          points: [],
          fdd_rules: [],
        },
      }),
    );
    expect(payload.sites[0].id).toBe("s1");
  });
});

describe("assignmentSummary", () => {
  it("counts bound points from rules and point tags", () => {
    const summary = assignmentSummary({
      sites: [],
      equipment: [],
      points: [
        { id: "p1", fdd_rule_ids: ["a"] },
        { id: "p2" },
      ],
      fdd_rules: [{ id: "b", bindings: { point_ids: ["p3"] } }],
    });
    expect(summary.ruleCount).toBe(1);
    expect(summary.boundPointCount).toBe(2);
    expect(summary.pointsWithRules).toBe(1);
  });
});
