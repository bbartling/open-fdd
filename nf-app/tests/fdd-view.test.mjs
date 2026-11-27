// node --test nf-app/tests/fdd-view.test.mjs - the FDD tab view model (static/fdd-view.js, 5.0.20 layout): result statuses,
// plain skip reasons, faults-first order, summary chips, the "show all" collapse, URL state and SI thresholds.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const ctx = vm.createContext({ console, URLSearchParams, URL, TextDecoder, atob, btoa });
for (const f of ["paging.js", "nf.js", "model.js", "plot-spec-data.js", "fdd-view.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
const get = (n) => vm.runInContext(n, ctx);
const equip = { name: "AHU-1", attrs: { id: "AHU-1" } };
const row = (id, extra = {}) => ({ rule: { id, description: id, parameters: {} }, equip, runnable: true, pointInputs: true, missing: [], ...extra });
const result = (value, attrs = {}) => ({ latest: value == null ? null : { double: value }, units: "h", rec: { attrs: { fddOutput: "fault_hours", fddWindowHours: "24", ...attrs } } });

test("statuses: fault, pass, skipped (no run proof, missing inputs, meter data), insufficient (stale, no covered time, no result)", () => {
  const of = (r, p) => get("fddEntryOf")(r, p);
  assert.deepEqual([of(row("A"), result(2.5, { fddStatus: "fault" })).status, of(row("A"), result(2.5, { fddStatus: "fault" })).faultHours], ["fault", 2.5]);
  assert.equal(of(row("B"), result(0, { fddStatus: "ok" })).status, "pass");
  const skip = of(row("C"), result(null, { fddStatus: "not-assessed", fddReason: "no_run_proof: no status or command bound" }));
  assert.equal(skip.status, "skipped");
  assert.match(skip.reason, /^no run proof/);
  assert.equal(skip.faultHours, null, "a skip has no hours (unknown, not zero)");
  const missing = of(row("D", { runnable: false, missing: ["discharge_air_static_pressure"] }), null);
  assert.deepEqual([missing.status, missing.reason], ["skipped", "missing inputs: discharge_air_static_pressure"]);
  assert.match(of(row("E", { runnable: false, pointInputs: false }), null).reason, /meter data/);
  assert.equal(of(row("F"), result(null, { fddStatus: "stale" })).status, "insufficient");
  assert.match(of(row("F"), result(null, { fddStatus: "stale" })).reason, /stale/);
  const off = of(row("G"), result(null, { fddStatus: "not-assessed", fddReason: "not running: no covered time" }));
  assert.deepEqual([off.status, off.reason], ["insufficient", "equipment off the whole window (nothing to assess)"]);
  assert.deepEqual([of(row("H"), null).status, of(row("H"), null).reason], ["insufficient", "no result written yet"]);
});

test("faults first by fault hours; pass and skipped collapse behind show all; a chip filter shows one status", () => {
  const of = (r, p) => get("fddEntryOf")(r, p);
  const entries = [of(row("P"), result(0, { fddStatus: "ok" })), of(row("F1"), result(1, { fddStatus: "fault" })),
    of(row("S", { runnable: false, missing: ["x"] }), null), of(row("F2"), result(4, { fddStatus: "fault" })), of(row("I"), null)];
  const vis = get("fddVisibleEntries");
  const def = vis(entries, {});
  assert.deepEqual(Array.from(def.shown, (e) => e.ruleId), ["F2", "F1", "I"]);
  assert.equal(def.hidden, 2);
  assert.deepEqual(Array.from(vis(entries, { showAll: true }).shown, (e) => e.ruleId), ["F2", "F1", "I", "P", "S"]);
  assert.deepEqual(Array.from(vis(entries, { filter: "skipped" }).shown, (e) => e.ruleId), ["S"]);
  const s = get("fddSummary")(entries);
  assert.deepEqual({ ...s.fault }, { count: 2, hours: 5 });
  assert.deepEqual([s.pass.count, s.skipped.count, s.insufficient.count], [1, 1, 1]);
});

test("URL state: equipment, open rule and filter round-trip; unknown filters are dropped", () => {
  const href = get("fddUrlWith")("https://nf.example/apps/static/open-fdd/?range.faults=24h#fdd", { equip: "AHU-1", rule: "CMD-1", filter: "fault" });
  const u = new URL(href);
  assert.equal(u.hash, "#fdd");
  assert.equal(u.searchParams.get("range.faults"), "24h", "the window (charts.js range keys) is kept");
  assert.deepEqual({ ...get("fddUrlState")(u.search) }, { equip: "AHU-1", rule: "CMD-1", filter: "fault" });
  assert.equal(get("fddUrlState")("?fdd.filter=bogus").filter, "");
  assert.ok(!new URL(get("fddUrlWith")(href, { equip: "AHU-1" })).searchParams.has("fdd.rule"), "closing the rule removes it");
});

test("SI thresholds come from the rule's tuning controls (labels, SI units), else the catalog parameters", () => {
  const controls = get("ofddPlotSpecData").rule_tuning.rules["VAV-3"].controls;
  const si = Array.from(get("fddSiParameters")({ id: "VAV-3", parameters: {} }, controls), (x) => ({ ...x }));
  const oat = si.find((x) => x.key === "reheat_oat");
  assert.equal(oat.unit, "°C");
  assert.ok(Math.abs(oat.value - 25.5556) < 1e-3);
  assert.equal(si.find((x) => x.key === "flow_on_min").unit, "L/s");
  assert.deepEqual(Array.from(get("fddSiParameters")({ parameters: { a: 1.5, b: "x" } }), (x) => x.key), ["a"]);
});

test("the FDD tab HTML: summary strip, one list, the open-rule panel, a tuning drawer, More collapsed; no all-equipment wording", () => {
  const html = readFileSync(new URL("index.html", dir), "utf8");
  const fdd = html.slice(html.indexOf('id="tab-fdd"'), html.indexOf("<!-- BACnet server"));
  for (const id of ["fddSummary", "fddList", "fddShowAll", "fddPlotPanel", "fddSiParams", "fddInputs", "fddDrawer", "fddTunersPanel", "fddMore", "fddLanes", "fddRows"]) assert.match(fdd, new RegExp(`id="${id}"`), id);
  assert.match(fdd, /<aside class="fdd-drawer" id="fddDrawer" hidden/);
  assert.match(fdd, /<details class="panel fdd-more" id="fddMore">/);
  const app = readFileSync(new URL("app.js", dir), "utf8");
  assert.ok(!/All equipment in scope|all-devices view/.test(app));
  assert.match(app, /fddEquipsInScope = \(\) => \(tabEquip\(\) \?/, "the FDD list is one equipment, never all");
});