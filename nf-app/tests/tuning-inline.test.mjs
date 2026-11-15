// Inline Tuners (static/tuning.js) end to end against the real tuning hook over an in-memory rule_config with real
// transaction semantics: the save message survives the reload (#1611), a stale equipment load is cancelled (#1613),
// one Save / Reset is one atomic hook call for rule parameters + SV-LIMITS, and an unknown outcome reconciles (#1622).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { ruleConfigClient } from "./fixtures/rule-config-client.mjs";

const require = createRequire(import.meta.url);
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../static/fdd-catalog.json", import.meta.url), "utf8"));
const specCtx = vm.createContext({});
vm.runInContext(readFileSync(new URL("../static/plot-spec-data.js", import.meta.url), "utf8"), specCtx);
globalThis.ofddPlotSpecData = specCtx.ofddPlotSpecData;
const tuning = require("../static/tuning.js");
const tuningHook = require("../hooks/tuning.js");

const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, { id, value: "", textContent: "", innerHTML: "", className: "", dataset: {}, querySelector: () => null });
  return els.get(id);
};
globalThis.document = { getElementById: (id) => el(id) };
globalThis.confirm = () => true;

const SITE = "s1", EQUIP = "AHU-9", RULE = "SV-RANGE", SCOPE = `equip:${EQUIP}`;
const ctxFor = (equip = EQUIP) => ({ site: SITE, equip, equipLabel: equip, ruleId: RULE, bound: { sat: [{ uuid: "u1" }] }, catalog });
const panel = () => el("fddTunersPanel").innerHTML;
const status = () => tuning._state().status;   // what every redraw renders into #tunStatus

function server(opts = {}) {
  const client = ruleConfigClient(opts);
  const calls = [];
  const hook = (args) => tuningHook.handle({ sdk: { logEvent: () => {} }, args, connect: async () => client, pack });
  tuning._setTransport(async (args) => { calls.push(args); return hook(args); });
  return { client, calls, hook, writes: () => calls.filter((a) => ["save", "reset", "rollback"].includes(a.action)) };
}
const settle = () => new Promise((ok) => setImmediate(ok));
async function open(ctx = ctxFor()) {
  tuning.cancelInline();
  tuning.renderInline(ctx);
  for (let i = 0; i < 20 && /Loading/.test(panel()); i++) await settle();
}
const unitOf = (key) => panel().match(new RegExp(`data-param="${key}" data-unit="([^"]+)"`))[1];
function edit({ param, sweep } = {}) {
  const host = el("fddTunersPanel");
  if (param) host.oninput({ target: { dataset: { param: param[0], unit: unitOf(param[0]) }, value: String(param[1]) } });
  if (sweep) host.oninput({ target: { dataset: { role: sweep[0], field: sweep[1], unit: sweep[3] }, value: String(sweep[2]) } });
}
const activeRev = (client, rid) => (client.rows.find((r) => r.rule_id === rid && r.scope_key === SCOPE && r.active) || {}).revision || 0;

test("#1611: the save confirmation survives the reload that follows the save", async () => {
  server();
  await open();
  edit({ param: ["confirm_min", 20] });
  await el("tunSave").onclick();
  assert.match(status(), /Saved revision/);
  assert.match(el("tunStatus").textContent, /Saved revision/, "the live banner");
  tuning.renderInline(ctxFor());   // any later redraw keeps it
  assert.match(panel(), /id="tunStatus" role="status">Saved revision/);
});

test("#1622: one Save writes rule parameters and SV-LIMITS in one hook call, or neither", async () => {
  const s = server();
  await open();
  edit({ param: ["confirm_min", 20], sweep: ["discharge-air-temp", "hi", 30, "degC"] });
  await el("tunSave").onclick();
  assert.equal(s.writes().length, 1, JSON.stringify(s.writes()));
  assert.equal(activeRev(s.client, RULE), 1);
  assert.equal(activeRev(s.client, "SV-LIMITS"), 1);
  assert.match(status(), /Saved/);

  // someone else saves SV-LIMITS meanwhile; this tab's next Save is refused as a whole
  await s.hook({ action: "save", site: SITE, scope: SCOPE, rule_id: "SV-LIMITS", overrides: JSON.stringify({ version: 1, roles: {} }), expected_revision: 1 });
  edit({ param: ["confirm_min", 25], sweep: ["discharge-air-temp", "hi", 31, "degC"] });
  await el("tunSave").onclick();
  assert.match(status(), /conflict/i);
  assert.equal(activeRev(s.client, RULE), 1, "rule parameters were not written either");
  assert.equal(activeRev(s.client, "SV-LIMITS"), 2);
});

test("#1622: a failing second write rolls back the first (hook level, both actions)", async () => {
  const s = server({ failInsert: (rid) => rid === "SV-LIMITS" });
  for (const action of ["save", "reset"]) {
    const ans = await s.hook({ action, site: SITE, scope: SCOPE, rule_id: RULE, overrides: action === "save" ? JSON.stringify({ version: 1, params: { confirm_min: 20 } }) : undefined,
      expected_revision: 0, limits_overrides: JSON.stringify({ version: 1, roles: { "discharge-air-temp": { hi: 30 } } }), limits_expected_revision: 0 });
    assert.equal(ans.ok, false, action);
    assert.match(ans.error, /simulated write failure/);
    assert.equal(s.client.rows.length, 0, `${action}: nothing stored`);
  }
});

test("#1622: Reset is one atomic call too, and an unknown outcome reloads the committed state", async () => {
  const s = server();
  await open();
  edit({ param: ["confirm_min", 20], sweep: ["discharge-air-temp", "hi", 30, "degC"] });
  await el("tunSave").onclick();
  const before = s.writes().length;
  await el("tunReset").onclick();
  assert.equal(s.writes().length - before, 1, "reset = one hook call");
  assert.equal(activeRev(s.client, RULE), 2);
  assert.equal(activeRev(s.client, "SV-LIMITS"), 2);
  assert.match(status(), /Reset/);

  // the hook commits but the answer is lost on the way back
  tuning._setTransport(async (args) => {
    const ans = await s.hook(args);
    if (args.action === "save") throw new Error("network error");
    return ans;
  });
  edit({ param: ["confirm_min", 30] });
  await el("tunSave").onclick();
  assert.equal(activeRev(s.client, RULE), 3, "the write did commit");
  assert.match(status(), /unknown/i);
  assert.match(status(), /revision 3/);
});

test("#1613: switching equipment cancels the open Tuners; a late answer for the old equipment draws nothing", async () => {
  const s = server();
  let release;
  const gate = new Promise((ok) => { release = ok; });
  tuning._setTransport(async (args) => { await gate; return s.hook(args); });
  tuning.renderInline(ctxFor("AHU-OLD"));
  tuning.cancelInline();
  release();
  for (let i = 0; i < 20; i++) await settle();
  assert.equal(panel(), "");
  assert.equal(tuning._state().context, null);
});