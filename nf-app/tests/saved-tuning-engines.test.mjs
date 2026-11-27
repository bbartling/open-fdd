// #1798: DuckDB reads saved Timescale tuning (fdd.rule_config) and honors the SQL the hook passes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine, releaseDuckDb } = require("../hooks/lib/engines.js");

const pack = {
  helper_functions: [],
  duckdb_helpers_sql: "SELECT 1",
  contract: { history: [
    { name: "equipment_id", type: "text" },
    { name: "timestamp_utc", type: "timestamp" },
  ] },
  rules: {
    R1: { sql: "SELECT 'pack' AS equipment_id", timeline_sql: "SELECT 'pack' AS equipment_id" },
  },
};

const input = { history: [{ equipment_id: "E", ts: Date.UTC(2026, 10, 5) }] };

test("duckdb: a tuning store is readable, and query uses the saved SQL", async () => {
  const rows = [{ site_id: "site-a", rule_id: "R1", scope_key: "site", revision: 2, parameters: { version: 1, params: { n: 1 } } }];
  const client = { async query() { return { rows }; } };
  const eng = await createEngine({ kind: "duckdb", pack, tuningClient: client });
  try {
    const got = await eng.ruleConfigOverrides();
    assert.equal(got.length, 1);
    assert.equal(got[0].rule_id, "R1");
    assert.equal(got[0].revision, 2);
    await eng.load(input);
    const packed = await eng.query("R1");
    assert.equal(packed[0].equipment_id, "pack");
    const tuned = await eng.query("R1", { sql: "SELECT 'tuned' AS equipment_id" });
    assert.equal(tuned[0].equipment_id, "tuned");
    const tl = await eng.timeline("R1", { timeline_sql: "SELECT 'tuned-tl' AS equipment_id" });
    assert.equal(tl[0].equipment_id, "tuned-tl");
  } finally { await eng.close(); await releaseDuckDb(); }
});

test("duckdb: no store means no overrides reader; a connection object exposes one and is not opened here", async () => {
  const plain = await createEngine({ kind: "duckdb", pack });
  try { assert.equal(plain.ruleConfigOverrides, undefined); } finally { await plain.close(); }
  const withStore = await createEngine({ kind: "duckdb", pack, config: { host: "db.example", database: "fdd", user: "fdd" } });
  try { assert.equal(typeof withStore.ruleConfigOverrides, "function"); } finally { await withStore.close(); await releaseDuckDb(); }
});
