// Every chart of the archived central UI must be accounted for in the NF app (nf-app/rcx-parity.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const OLD = path.join(ROOT, "archive/central-v4/services/central/static/product");
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

const oldBuilders = () => {
  const dir = path.join(OLD, "assets/js");
  const out = new Set();
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".js"))) {
    for (const m of fs.readFileSync(path.join(dir, f), "utf8").matchAll(/export function (\w+Option)\b/g)) out.add(`${f}#${m[1]}`);
  }
  // chart-parity.json "new_renderer" entries (incl. non-*Option helpers such as expandFddPlotRoles)
  for (const c of JSON.parse(fs.readFileSync(path.join(OLD, "chart-parity.json"), "utf8")).charts) {
    if (c.new_renderer) out.add(c.new_renderer.split("/").pop());
  }
  return out;
};

test("parity: every old chart builder is mapped", { skip: !fs.existsSync(OLD) && "archive not present" }, () => {
  const missing = [...oldBuilders()].filter((k) => !parity.builders[k]);
  assert.deepEqual(missing, [], `old charts with no NF-app home: ${missing.join(", ")}`);
});

test("parity: all 18 RCx presets map to registered views", { skip: !fs.existsSync(OLD) && "archive not present" }, () => {
  const src = fs.readFileSync(path.join(OLD, "assets/js/rcx-catalog.js"), "utf8");
  const ids = [...src.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  assert.equal(ids.length, 18);
  const app = loadApp();
  for (const id of ids) {
    assert.ok(parity.presets[id], `preset ${id} not in rcx-parity.json`);
    assert.ok(app.ids.has(parity.presets[id]), `preset ${id} -> view ${parity.presets[id]} is not registered`);
  }
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
