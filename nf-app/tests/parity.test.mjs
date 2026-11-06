// Every chart of the archived central UI must be accounted for in the NF app (nf-app/rcx-parity.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const STATIC = path.join(ROOT, "nf-app/static");
const parity = JSON.parse(fs.readFileSync(path.join(ROOT, "nf-app/rcx-parity.json"), "utf8"));

/** Load the app's chart modules (no DOM, no network) and return the registry + globals. */
function loadApp() {
  const ctx = vm.createContext({
    console, FAULT_LANE: { lineStyle: {}, areaStyle: {} }, fetchSeries: async () => new Map(),
    pickWindow: () => 300, ofddChart: () => ({}), ofddRender: () => {}, document: {}, window: {},
  });
  ctx.globalThis = ctx;
  for (const f of ["model.js", "fdd.js", "rcx.js", "fdd-plots.js", "rcx-overview.js", "rcx-presets.js", "energy.js"]) {
    vm.runInContext(fs.readFileSync(path.join(STATIC, f), "utf8"), ctx, { filename: f });
  }
  return { ids: new Set(Array.from(vm.runInContext("RCX_VIEWS", ctx), (v) => v.id)), has: (name) => vm.runInContext(`typeof ${name}`, ctx) === "function" };
}

// The 4.x central UI was removed in 5.0 (it lives at tag v4.0.11-central). Its chart inventory is
// frozen in rcx-parity.json: 40 builders + 18 presets. These counts must not shrink.
const BUILDERS_4X = 40;
const PRESETS_4X = 18;

test("parity: the frozen 4.x chart inventory is fully mapped", () => {
  assert.ok(Object.keys(parity.builders).length >= BUILDERS_4X, "a 4.x chart builder lost its mapping");
  assert.equal(Object.keys(parity.presets).length, PRESETS_4X);
});

test("parity: all 18 RCx presets map to registered views", () => {
  const app = loadApp();
  for (const [id, view] of Object.entries(parity.presets)) assert.ok(app.ids.has(view), `preset ${id} -> view ${view} is not registered`);
});

test("parity: mapped views and functions exist in the app", () => {
  const app = loadApp();
  for (const [old, m] of Object.entries(parity.builders)) {
    assert.ok(m.views || m.fn, `${old}: needs views or fn`);
    for (const id of m.views || []) assert.ok(app.ids.has(id), `${old} -> view ${id} is not registered`);
    if (m.fn) assert.ok(app.has(m.fn), `${old} -> ${m.fn} is not a global function`);
  }
  for (const [id] of Object.entries(parity.fault_lanes).filter(([k]) => !k.startsWith("_"))) {
    assert.ok(app.ids.has(id), `fault lane view ${id} is not registered`);
  }
  for (const [what, why] of Object.entries(parity.not_ported)) assert.ok(why && why.length > 20, `not_ported "${what}" needs a reason`);
});

test("parity: fault-lane rules exist in the rule catalog", () => {
  const rules = new Set(JSON.parse(fs.readFileSync(path.join(STATIC, "fdd-catalog.json"), "utf8")).rules.map((r) => r.id));
  for (const [view, ids] of Object.entries(parity.fault_lanes)) {
    if (view.startsWith("_")) continue;
    for (const id of ids) assert.ok(rules.has(id), `${view}: unknown rule ${id}`);
  }
});
