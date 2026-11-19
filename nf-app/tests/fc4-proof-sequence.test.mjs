// #1631: FC4 counts operating-state entries over PROVEN samples only. A transition across unproven time is not an entry,
// so an unproven flap cannot push an hour over DELTA_OS_MAX. Twin: open_fdd/rules/cookbook_catalog.py fc4
// (tests/test_fc4_proof_sequence.py pins the same two cases in pandas).
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

// Four hours at five minutes, fan on. The cooling valve alternates 0.5 / 0 every sample (12 state changes an hour).
// `proofWhen(i)`: the run proof of sample i.
function input(proofWhen) {
  const history = [];
  for (let i = 0; i <= 48; i++) {
    history.push({ equipment_id: "ahu-1", ts: START + i * 300_000, run_proof: proofWhen(i) ? 1 : 0, fan_status: 1,
      fan_cmd: 1, clg_valve_pct: i % 2 ? 0 : 0.5, htg_valve_pct: 0, oa_damper_pct: 0 });
  }
  const cols = ["run_proof", "fan_status", "fan_cmd", "clg_valve_pct", "htg_valve_pct", "oa_damper_pct"];
  return { historyColumns: cols.map((name) => ({ name, type: "double" })), history, weather: [], sensorHistory: [] };
}

// FC4's shipped 60 min confirmation would hide the entry count (alternating proven samples never confirm), so the pack is
// run with confirmation 0: fault time is then exactly the proven samples of the hours the entry count flags.
const unconfirmed = (pack) => {
  const copy = JSON.parse(JSON.stringify(pack));
  assert.match(copy.rules.FC4.sql, /streak_elapsed >= 3600/);
  copy.rules.FC4.sql = copy.rules.FC4.sql.replace(/streak_elapsed >= 3600/g, "streak_elapsed >= 0");
  return copy;
};

async function fc4(kind, proofWhen) {
  const eng = await createEngine({ kind, pack: unconfirmed(PACKS[kind]) });
  try {
    await eng.load(input(proofWhen));
    const [row] = await eng.query("FC4");
    return Number(row.fault_hours);
  } finally {
    await eng.close();
  }
}

for (const kind of ["pglite", "sqlite"]) {
  test(`${kind}: proven hunting is a fault`, async () => {
    assert.ok(await fc4(kind, () => true) > 2);
  });
  test(`${kind}: the valve flaps only across unproven samples -> no entries, no fault`, async () => {
    // proof ON exactly on the cooling samples: the proven sequence is one constant state
    assert.equal(await fc4(kind, (i) => i % 2 === 0), 0);
  });
}
