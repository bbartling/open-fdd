// #1631: when a run-proof gated rule has no proof (every run_proof sample NULL), its summary row is SKIPPED (fault_hours
// NULL, covered_hours 0). Its timeline must give the same answer: no rows, not a day of held, never-confirmed rows that
// reads as assessed. scripts/nf/build_sql_pack.py build_timeline_pg filters equipment the rule's rp CTE marks
// no_run_proof.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const PACKS = {
  pglite: JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8")),
  sqlite: JSON.parse(readFileSync(new URL("../rules/pack-sqlite.json", import.meta.url), "utf8")),
};
const START = Date.UTC(2026, 0, 1);

function input(runProof) {
  const history = [];
  for (let m = 0; m <= 360; m += 5) {
    history.push({ equipment_id: "ahu-1", ts: START + m * 60_000, run_proof: runProof, fan_status: 1, sat: 20, sat_sp: 12 });
  }
  return { historyColumns: ["run_proof", "fan_status", "sat", "sat_sp"].map((name) => ({ name, type: "double" })),
    history, weather: [], sensorHistory: [] };
}

test("every run-proof gated timeline filters equipment with no proof", () => {
  for (const [rid, r] of Object.entries(PACKS.pglite.rules)) {
    if (!r.timeline_sql || !/\bno_run_proof\b/.test(r.sql)) continue;
    assert.match(r.timeline_sql, /NOT IN \(SELECT rpx\.equipment_id FROM rp rpx WHERE rpx\.no_run_proof = 1\)/, rid);
  }
});

for (const kind of ["pglite", "sqlite"]) {
  test(`${kind}: no proof -> SKIPPED summary and an empty timeline; with proof the timeline is there`, async () => {
    for (const [proof, expectRows] of [[null, false], [1, true]]) {
      const eng = await createEngine({ kind, pack: PACKS[kind] });
      try {
        await eng.load(input(proof));
        const [row] = await eng.query("AHU-SATDEV");
        const tl = await eng.timeline("AHU-SATDEV");
        if (expectRows) {
          assert.ok(row.covered_hours > 5);
          assert.ok(tl.length > 0);
        } else {
          assert.equal(row.fault_hours, null);
          assert.equal(row.covered_hours, 0);
          assert.equal(tl.length, 0, "the timeline gives the same answer as the summary");
        }
      } finally {
        await eng.close();
      }
    }
  });
}
