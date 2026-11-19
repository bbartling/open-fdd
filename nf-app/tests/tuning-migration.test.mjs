// #1673: SV-STALE's one visible duration is stale_after_hours. Saved documents from before the split migrate per scope:
// max_silence_hours -> stale_after_hours (an explicit stale_after_hours in the same document wins); stale_hours,
// stale_tol, confirm_min and the motor-status gate are retired (ignored and reported when read, rejected on a new write).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const rt = require("../hooks/lib/rule-tuning.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const tpl = pack.rule_tuning_templates.rules["SV-STALE"];
const { controls, legacy } = tpl;
const doc = (params) => ({ version: 1, params });
const merge = (site, equip) => rt.mergeRuleParams(controls, site && doc(site), equip && doc(equip), "SV-STALE", legacy);

test("the template exposes exactly one SV-STALE control and its legacy map", () => {
  assert.deepEqual(Object.keys(controls), ["stale_after_hours"]);
  assert.equal(controls.stale_after_hours.default, 0.5, "initialised from the old gap default, not the 2 h value-span window");
  assert.deepEqual(legacy.aliases, { max_silence_hours: "stale_after_hours" });
  for (const k of ["stale_hours", "stale_tol", "confirm_min", "require_run_proof", "require_operational_gate"]) assert.ok(legacy.retired.includes(k), k);
});

test("a saved legacy max_silence_hours becomes stale_after_hours; the new key wins in the same document", () => {
  const legacyOnly = merge({ max_silence_hours: 2 }, null);
  assert.equal(legacyOnly.effective.stale_after_hours, 2);
  assert.equal(legacyOnly.sources.stale_after_hours, "site");
  assert.deepEqual(legacyOnly.migration, [{ layer: "site", key: "max_silence_hours", action: "renamed", to: "stale_after_hours", value: 2 }]);
  const both = merge({ max_silence_hours: 2, stale_after_hours: 1 }, null);
  assert.equal(both.effective.stale_after_hours, 1);
  assert.equal(both.migration[0].action, "superseded");
});

test("stale_hours-only and stale_tol records are retired, not reinterpreted as a gap setting", () => {
  const r = merge({ stale_hours: 6, stale_tol: 0.1 }, null);
  assert.equal(r.effective.stale_after_hours, 0.5, "shipped default kept");
  assert.equal(r.sources.stale_after_hours, "shipped");
  assert.deepEqual(r.migration.map((m) => [m.key, m.action]), [["stale_hours", "retired"], ["stale_tol", "retired"]]);
});

test("each scope migrates before precedence: an equipment legacy key beats the site's new key", () => {
  const r = merge({ stale_after_hours: 1 }, { max_silence_hours: 3 });
  assert.equal(r.effective.stale_after_hours, 3);
  assert.equal(r.sources.stale_after_hours, "equip");
  const siteLegacyEquipNew = merge({ max_silence_hours: 3 }, { stale_after_hours: 0.25 });
  assert.equal(siteLegacyEquipNew.effective.stale_after_hours, 0.25);
  // resetting the equipment scope (no equipment document) falls back to the site's migrated value
  assert.equal(merge({ max_silence_hours: 3 }, null).effective.stale_after_hours, 3);
  // a reset site with an equipment override keeps the equipment value
  assert.equal(merge(null, { max_silence_hours: 4 }).effective.stale_after_hours, 4);
});

test("an invalid stored legacy value is reported, not clamped; an invalid new value is rejected", () => {
  const r = merge({ max_silence_hours: 99 }, null);
  assert.equal(r.effective.stale_after_hours, 0.5);
  assert.equal(r.migration[0].action, "invalid");
  assert.throws(() => merge({ stale_after_hours: 99 }, null), /outside/);
});

test("a new write rejects retired keys, NaN, booleans and out-of-range values atomically; the alias maps", () => {
  const write = (params) => rt.normalizeRuleOverride(doc(params), controls, "SV-STALE", { legacy });
  for (const k of ["stale_hours", "stale_tol", "confirm_min", "require_run_proof", "require_operational_gate"]) {
    assert.throws(() => write({ [k]: 1 }), /retired/, k);
  }
  assert.throws(() => write({ stale_after_hours: NaN }), /finite/);
  assert.throws(() => write({ stale_after_hours: true }), /finite/);
  assert.throws(() => write({ stale_after_hours: 0.1 }), /outside/);
  assert.throws(() => write({ stale_after_hours: 1, stale_hours: 2 }), /retired/, "one bad key fails the whole document");
  assert.deepEqual(write({ max_silence_hours: 1 }).params, { stale_after_hours: 1 });
  assert.deepEqual(write({ stale_after_hours: 1.5 }).params, { stale_after_hours: 1.5 });
});

test("the migrated value renders into the SQL the next run executes", () => {
  const r = merge({ stale_hours: 6 }, { max_silence_hours: 2 });
  const values = rt.resolvePlaceholders(rt.ruleDefaults(pack.rule_tuning_templates, tpl), controls, r.effective, r.overrideKeys, pack.poll_seconds);
  const sql = rt.renderRuleSql(tpl.sql, values, "SV-STALE");
  assert.ok(sql.includes("dt_seconds > 7200"), "2 h threshold");
  assert.ok(!sql.includes("{{"));
});
