// #1671: at most one user-facing delay/duration timer per rule. The startup and mode-change delays, the active
// coverage floors, the retired operational gate, join plumbing (web cadence / as-of margin), gap cutoffs and the
// stacked confirm delay on rolling-window rules are fixed internal constants at their shipped values. Saved
// documents that still carry one of those keys keep working: the key is ignored and reported when read, and a new
// save rejects it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const rt = require("../hooks/lib/rule-tuning.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const tplRoot = pack.rule_tuning_templates;
const TIME_UNITS = new Set(["min", "h", "s", "sec"]);
const RETIRED = ["startup_delay_min", "mode_delay_min", "minimum_active_coverage_pct", "minimum_coverage_pct",
  "require_operational_gate", "web_asof_margin_seconds", "web_cadence_seconds", "max_silence_hours", "persistence_min",
  "max_gap_hours"];
const WINDOW_RULES = { "SV-FLATLINE": "flatline_hours", "VAV-4": "sustain_hours", "VAV-7": "fixed_flow_hours", "PID-HUNT-1": "window_hours" };

const render = (ruleId, params, { stored = false } = {}) => {
  const tpl = tplRoot.rules[ruleId];
  const merged = rt.mergeRuleParams(tpl.controls, params && { version: 1, params }, null, ruleId, tpl.legacy);
  if (!stored) assert.deepEqual(merged.migration, []);
  const values = rt.resolvePlaceholders(rt.ruleDefaults(tplRoot, tpl), tpl.controls, merged.effective, merged.overrideKeys, pack.poll_seconds);
  return { sql: rt.renderRuleSql(tpl.sql, values, ruleId), merged };
};

test("every rule exposes at most one time control", () => {
  for (const [ruleId, tpl] of Object.entries(tplRoot.rules)) {
    const timers = Object.values(tpl.controls).filter((c) => TIME_UNITS.has(c.unit)).map((c) => c.key);
    assert.ok(timers.length <= 1, `${ruleId} exposes ${timers.join(", ")}`);
  }
});

test("no rule exposes a retired delay, coverage floor or join/gap key", () => {
  for (const [ruleId, tpl] of Object.entries(tplRoot.rules)) {
    for (const k of RETIRED) {
      if (ruleId === "SV-STALE" && k === "max_silence_hours") continue;   // #1673: an alias of stale_after_hours
      assert.ok(!(k in tpl.controls), `${ruleId} still exposes ${k}`);
    }
  }
});

test("rolling-window rules keep only the window duration; the confirm delay is internal", () => {
  for (const [ruleId, windowKey] of Object.entries(WINDOW_RULES)) {
    const tpl = tplRoot.rules[ruleId];
    assert.ok(windowKey in tpl.controls, `${ruleId} keeps ${windowKey}`);
    assert.ok(!("confirm_min" in tpl.controls), `${ruleId} no longer exposes confirm_min`);
    assert.ok(tpl.legacy.retired.includes("confirm_min"));
    assert.ok(Number.isFinite(tpl.internal.CONFIRM_SECONDS), `${ruleId} pins its confirm delay internally`);
  }
});

test("each internal constant renders exactly the shipped SQL (results do not change)", () => {
  for (const [ruleId, tpl] of Object.entries(tplRoot.rules)) {
    if (!tpl.internal) continue;
    if (["SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-RATE"].includes(ruleId)) continue;   // role-limit fragment rules: rule-tuning.test.mjs
    assert.equal(render(ruleId, null).sql, pack.rules[ruleId].sql, ruleId);
  }
});

test("a saved retired key is ignored and reported; a new save rejects it", () => {
  const cases = [["FC1", "mode_delay_min", 20], ["FC1", "startup_delay_min", 5], ["VAV-1", "minimum_active_coverage_pct", 50],
    ["OAT-METEO", "web_asof_margin_seconds", 900], ["SV-RANGE", "max_silence_hours", 12], ["VAV-4", "confirm_min", 30],
    ["PID-HUNT-1", "minimum_coverage_pct", 50], ["SV-RATE", "max_gap_hours", 2], ["AHU-DUCTHI", "require_operational_gate", 0]];
  for (const [ruleId, key, value] of cases) {
    const tpl = tplRoot.rules[ruleId];
    assert.ok(tpl.legacy.retired.includes(key), `${ruleId}.${key} is listed as retired`);
    const { sql, merged } = render(ruleId, { [key]: value }, { stored: true });
    assert.deepEqual(merged.migration, [{ layer: "site", key, action: "retired", value }], `${ruleId}.${key}`);
    assert.ok(!(key in merged.effective));
    if (!["SV-RANGE", "SV-RATE"].includes(ruleId)) assert.equal(sql, pack.rules[ruleId].sql, `${ruleId}: the stored ${key} no longer changes the SQL`);
    assert.throws(() => rt.normalizeRuleOverride({ version: 1, params: { [key]: value } }, tpl.controls, ruleId, { legacy: tpl.legacy }),
      /was retired/, `${ruleId}.${key} is rejected on a new write`);
  }
});

test("the surviving timer still tunes the SQL", () => {
  assert.notEqual(render("FC1", { confirm_min: 37 }).sql, pack.rules.FC1.sql);
  assert.ok(render("FC1", { confirm_min: 37 }).sql.includes(">= 2220"));
  assert.notEqual(render("VAV-4", { sustain_hours: 3 }).sql, pack.rules["VAV-4"].sql);
});
