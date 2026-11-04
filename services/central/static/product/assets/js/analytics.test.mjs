import { analyticsBody } from "./analytics.js";
import { confirmMinForRule, numericParamsFromSession } from "./rule-params.js";
import test from "node:test";
import assert from "node:assert/strict";

test("analyticsBody sends flattened query fields", () => {
  const body = analyticsBody("SITE_A", ["AHU_1"], 24, 1500);
  assert.equal(body.building_id, "SITE_A");
  assert.deepEqual(body.equipment_ids, ["AHU_1"]);
  assert.equal(body.max_points, 1500);
  assert.ok(body.start);
  assert.ok(body.end);
  assert.equal(body.query, undefined);
});

test("analyticsBody accepts sampling window object", () => {
  const body = analyticsBody("SITE_A", ["AHU_1"], { start: "2026-01-01T00:00:00Z", end: "2026-02-01T00:00:00Z" });
  assert.equal(body.start, "2026-01-01T00:00:00Z");
  assert.equal(body.end, "2026-02-01T00:00:00Z");
});
