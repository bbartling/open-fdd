// #1672: the per-rule tuner contract in the Full edition's inline Tuners. Every catalog control renders, grouped
// (duration, thresholds, tolerances, other, then the gates); numeric controls are a slider on the SI step grid plus a
// number box in display units; require_run_proof is the "Require motor status" checkbox after the numeric tuners.
// Values snap to the catalog step, low/high pairs stay ordered, and invalid saves fail closed in the panel and the hook.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { ruleConfigClient } from "./fixtures/rule-config-client.mjs";

const require = createRequire(import.meta.url);
const rt = require("../hooks/lib/rule-tuning.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../static/fdd-catalog.json", import.meta.url), "utf8"));
const specCtx = vm.createContext({});
vm.runInContext(readFileSync(new URL("../static/plot-spec-data.js", import.meta.url), "utf8"), specCtx);
globalThis.ofddPlotSpecData = specCtx.ofddPlotSpecData;
const tuning = require("../static/tuning.js");
const tuningHook = require("../hooks/tuning.js");
const tpls = pack.rule_tuning_templates.rules;

const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, { id, value: "", textContent: "", innerHTML: "", className: "", dataset: {}, querySelector: () => null });
  return els.get(id);
};
globalThis.document = { getElementById: (id) => el(id) };
globalThis.confirm = () => true;

const SITE = "s1", EQUIP = "AHU-9", SCOPE = `equip:${EQUIP}`;
const panel = () => el("fddTunersPanel").innerHTML;
function server() {
  const client = ruleConfigClient();
  const calls = [];
  const hook = (args) => tuningHook.handle({ sdk: { logEvent: () => {} }, args, connect: async () => client, pack });
  tuning._setTransport(async (args) => { calls.push(args); return hook(args); });
  return { client, hook, writes: () => calls.filter((a) => ["save", "reset", "rollback"].includes(a.action)) };
}
const settle = () => new Promise((ok) => setImmediate(ok));
async function open(ruleId) {
  tuning.cancelInline();
  tuning.renderInline({ site: SITE, equip: EQUIP, equipLabel: EQUIP, ruleId, bound: {}, catalog });
  for (let i = 0; i < 20 && /Loading/.test(panel()); i++) await settle();
}
const unitOf = (key) => panel().match(new RegExp(`data-param="${key}" data-unit="([^"]+)"`))[1];
const saved = (client, ruleId) => (client.rows.find((r) => r.rule_id === ruleId && r.scope_key === SCOPE && r.active) || {}).parameters;

test("73 rules have controls; FAN-RUNTIME-HOURS and AVG-ZONE-TEMP have none", () => {
  const ids = pack.rule_tuning_templates ? Object.keys(pack.rules) : [];
  const withControls = ids.filter((id) => tpls[id] && Object.keys(tpls[id].controls).length);
  assert.equal(withControls.length, 73);   // + COIL-PERF (#1724); - FCU-HTG-COIL, FCU-CLG-COIL, VAV-REHEAT (#1641)
  assert.deepEqual(ids.filter((id) => !withControls.includes(id)).sort(), ["AVG-ZONE-TEMP", "FAN-RUNTIME-HOURS"]);
});

test("every rule groups its controls: at most one duration, gates last, motor status is a labelled boolean", () => {
  for (const [ruleId, tpl] of Object.entries(tpls)) {
    const groups = rt.groupControls(tpl.controls);
    assert.deepEqual(groups.flatMap((g) => g.keys).sort(), Object.keys(tpl.controls).sort(), `${ruleId}: every control shows once`);
    const dur = groups.find((g) => g.id === "duration");
    assert.ok(!dur || dur.keys.length === 1, `${ruleId} has one timer`);
    const gates = groups.findIndex((g) => g.id === "gates");
    assert.ok(gates === -1 || gates === groups.length - 1, `${ruleId}: the gates follow the numeric tuners`);
    if (tpl.controls.require_run_proof) {
      assert.equal(tpl.controls.require_run_proof.kind, "boolean");
      assert.equal(tpl.controls.require_run_proof.label, "Require motor status");
      assert.ok(groups[gates].keys.includes("require_run_proof"));
    }
  }
  assert.deepEqual(rt.groupControls(tpls.FC2.controls).map((g) => g.id), ["duration", "thresholds", "tolerances", "gates"]);
});

test("every shipped default survives snapToStep, including the 1.15 degF tolerances off the grid (#1726)", () => {
  let offGrid = 0, checked = 0;
  for (const [ruleId, tpl] of Object.entries(tpls)) {
    for (const [key, ctrl] of Object.entries(tpl.controls)) {
      if (typeof ctrl.default !== "number" || !(ctrl.step > 0)) continue;
      checked++;
      const grid = Number((ctrl.min + Math.round((ctrl.default - ctrl.min) / ctrl.step) * ctrl.step).toFixed(6));
      if (Math.abs(grid - ctrl.default) > 1e-9) offGrid++;
      assert.equal(rt.snapToStep(ctrl, ctrl.default), ctrl.default, `${ruleId}.${key}`);
    }
  }
  assert.ok(checked > 200 && offGrid >= 60, `checked ${checked}, off-grid ${offGrid}`);
});

test("near the default snaps to the default; a step away snaps to the grid (#1726)", () => {
  const c = { min: 0, max: 5.555555556, step: 0.138888889, default: 0.638888889 };   // 1.15 degF, step 0.25 degF
  assert.equal(rt.snapToStep(c, 0.65), 0.638888889);
  assert.equal(rt.snapToStep(c, 0.638888889 + 0.01), 0.638888889);
  assert.equal(rt.snapToStep(c, 0.7), 0.694444);              // closer to the grid point 1.25 degF
  assert.equal(rt.snapToStep(c, 0.4), 0.416667);
  assert.equal(rt.snapToStep({ ...c, default: 99 }, 0.65), 0.694444);   // an out-of-range default is ignored
});

test("snapToStep anchors the grid at min and clamps", () => {
  const c = { min: 22.222222, max: 29.444444, step: 0.277778 };
  assert.equal(rt.snapToStep(c, 24.055556), 24.166668);
  assert.equal(rt.snapToStep(c, 100), 29.444444);
  assert.equal(rt.snapToStep(c, -5), 22.222222);
  assert.equal(rt.snapToStep({ min: 0, max: 60, step: 5 }, 17), 15);
});

test("the panel renders grouped sliders and the motor-status checkbox after them", async () => {
  server();
  await open("FC1");
  const html = panel();
  const at = (g) => html.indexOf(`data-group="${g}"`);
  assert.ok(at("duration") >= 0 && at("thresholds") > at("duration") && at("gates") > at("thresholds"));
  for (const [key, ctrl] of Object.entries(tpls.FC1.controls)) {
    if (ctrl.kind === "boolean") assert.match(html, new RegExp(`type="checkbox" data-param-bool="${key}"`));
    else assert.match(html, new RegExp(`type="range"[^>]*data-param-range="${key}"[^>]*min="${ctrl.min}" max="${ctrl.max}" step="${ctrl.step}"`));
  }
  assert.match(html, /data-param-bool="require_run_proof" checked> <span>Require motor status<\/span>/);
  assert.doesNotMatch(html, /type="range"[^>]*require_run_proof/, "the gate is not a 0/1 slider");
});

test("moving a slider snaps to the step, mirrors into the number box, and saves SI for this equipment only", async () => {
  const s = server();
  await open("FC1");
  el("fddTunersPanel").oninput({ target: { dataset: { paramRange: "confirm_min", unit: unitOf("confirm_min") }, value: "17" } });
  assert.equal(el("tun-p-confirm_min").value, "15");
  await el("tunSave").onclick();
  assert.deepEqual(saved(s.client, "FC1").params, { confirm_min: 15 });
  const other = await s.hook({ action: "get", site: SITE, scope: "equip:AHU-10", rule_id: "FC1" });
  assert.equal(other.effective.params.confirm_min, tpls.FC1.controls.confirm_min.default, "another equipment keeps the default");
});

test("a typed imperial value is stored as SI on the step grid", async () => {
  const s = server();
  await open("VAV-1");
  assert.equal(unitOf("zone_t_hi"), "degF");
  el("fddTunersPanel").oninput({ target: { dataset: { param: "zone_t_hi", unit: "degF" }, value: "75.3" } });
  await el("tunSave").onclick();
  const si = saved(s.client, "VAV-1").params.zone_t_hi;
  const c = tpls["VAV-1"].controls.zone_t_hi;
  assert.ok(Math.abs((si - c.min) / c.step - Math.round((si - c.min) / c.step)) < 1e-4, `${si} is on the step grid`);
  assert.ok(Math.abs(si - 24.166667) < 1e-5);
});

test("a low above its high fails closed in the panel and in the hook", async () => {
  const s = server();
  await open("ECON-3");   // econ3_db_min (10-20 C) and econ3_db_max (18.3-26.7 C) overlap; VAV-1's zone ranges cannot cross
  const host = el("fddTunersPanel");
  host.oninput({ target: { dataset: { param: "econ3_db_min", unit: "degF" }, value: "68" } });
  host.oninput({ target: { dataset: { param: "econ3_db_max", unit: "degF" }, value: "66" } });
  await el("tunSave").onclick();
  assert.match(tuning._state().status, /must be below/);
  assert.equal(s.writes().length, 0, "nothing was sent");
  assert.equal(saved(s.client, "ECON-3"), undefined);
  const ans = await s.hook({ action: "save", site: SITE, scope: SCOPE, rule_id: "ECON-3", overrides: { version: 1, params: { econ3_db_min: 20, econ3_db_max: 19 } } });
  assert.equal(ans.ok, false);
  assert.match(ans.error, /must be below/);
  assert.equal(saved(s.client, "ECON-3"), undefined, "the hook wrote nothing");
});
