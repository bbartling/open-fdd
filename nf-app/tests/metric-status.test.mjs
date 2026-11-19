// #1707: statistic rules (no fault_hours output) are written as METRIC, never INCONCLUSIVE.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const ts = require("../hooks/lib/timescale.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const base = { runTs: "2026-10-15T00:00:00Z", equip: "e1", site: "s1", windowStart: "2026-10-14T00:00:00Z", windowEnd: "2026-10-15T00:00:00Z" };

test("the metric rules are exactly the run-proof-exempt statistics with no fault_hours output", () => {
  const metric = Object.entries(pack.rules).filter(([, r]) => !(r.output_columns || []).includes("fault_hours")).map(([id]) => id).sort();
  assert.deepEqual(metric, ["AVG-ZONE-TEMP", "FAN-RUNTIME-HOURS", "ZONE-COMFORT-PCT"]);
  const registry = readFileSync(new URL("../../sql/fdd/registry.yaml", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  for (const id of metric) {
    const block = registry.slice(registry.indexOf(`rule_id: ${id}\n`), registry.indexOf("rule_id:", registry.indexOf(`rule_id: ${id}\n`) + 10));
    assert.match(block, /run_proof: exempt/, id);
  }
});

test("toResultRow: a metric row is METRIC with no reason and keeps its numbers in metrics", () => {
  const r = ts.toResultRow({ ...base, ruleId: "ZONE-COMFORT-PCT", row: { equipment_id: "e1", comfort_pct: 87.5 }, metric: true });
  assert.equal(r.status, "METRIC");
  assert.equal(r.reason, null);
  assert.equal(r.fault_hours, null);
  assert.deepEqual(r.metrics, { comfort_pct: 87.5 });
});

test("toResultRow: a fault rule with no fault_hours is still INCONCLUSIVE, and a fault rule still scores", () => {
  const inc = ts.toResultRow({ ...base, ruleId: "FC1", row: { equipment_id: "e1" } });
  assert.equal(inc.status, "INCONCLUSIVE");
  assert.equal(inc.reason, "rule reports no fault_hours");
  assert.equal(ts.toResultRow({ ...base, ruleId: "FC1", row: { equipment_id: "e1", fault_hours: 2 } }).status, "FAULT");
  assert.equal(ts.toResultRow({ ...base, ruleId: "FC1", row: { equipment_id: "e1", fault_hours: 0 } }).status, "PASS");
});

test("SCHEMA_VERSION is 6 and install.sql marks 6 (#1707)", () => {
  assert.equal(ts.SCHEMA_VERSION, 6);
  const sql = readFileSync(new URL("../timescale/install.sql", import.meta.url), "utf8");
  assert.match(sql, /'schema_version', to_jsonb\(6\)\)/);
});
