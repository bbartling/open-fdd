// node --test nf-app/tests/metric-display.test.mjs - #1775: a METRIC result (AVG-ZONE-TEMP, ZONE-COMFORT-PCT,
// FAN-RUNTIME-HOURS; markers point,his,metric,fdd, fddStatus ok) shows on the FDD tab as a metric with its value and
// unit, never as "Insufficient - no result written yet" and never as a fault; the hook writes its SI unit.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
const X = require("../static/export.js");
const dir = new URL("../static/", import.meta.url);
const ctx = vm.createContext({ console, URLSearchParams, URL, TextDecoder, atob, btoa });
for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "rcx.js", "plot-spec-data.js", "fdd-view.js"]) {
  vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
}
const get = (n) => vm.runInContext(n, ctx);
const packs = ["pack-postgres.json"].map((f) => JSON.parse(readFileSync(new URL(`../rules/${f}`, import.meta.url), "utf8")));
const METRIC_IDS = ["AVG-ZONE-TEMP", "FAN-RUNTIME-HOURS", "ZONE-COMFORT-PCT"];

const site = "site-a";
const equipRec = { uuid: "eq-uuid-1", name: "VAV-1", attrs: { id: "VAV-1", siteRef: site, dis: "VAV-1", markers: "vav,equip" } };
const ruleOf = (id) => ({ id, description: id });
const row = (id, extra = {}) => ({ rule: { id, description: id, parameters: {} }, equip: equipRec, runnable: true, pointInputs: true, missing: [], ...extra });

/** A result point as NF returns it, from the hook's own model record (+ latest value). */
function resultPoint(ruleId, rowValues, { latest, unit } = {}) {
  const packRule = packs[0].rules[ruleId];
  const out = hook.resultValue(packRule, rowValues);
  const [, model] = hook.resultRecords({ equipRec, siteId: site, rule: ruleOf(ruleId), out, shared: { idOf: (r) => r.attrs.id },
    windowHours: 24, key: equipRec.uuid, runIso: "2026-11-24T12:00:00Z" });
  const attrs = unit === undefined ? model.attrs : { ...model.attrs, unit };
  const v = latest === undefined ? out.value : latest;
  return get("toPoint")({ uuid: model.uuid, name: model.name, attrs, latestValue: v == null ? null : { double: v } });
}

test("the hook writes each metric output with its SI unit (same as docs_units OUTPUT_COLUMNS)", () => {
  const doc = readFileSync(new URL("../../scripts/nf/docs_units.py", import.meta.url), "utf8");
  const docUnit = (col) => (doc.match(new RegExp(`"${col}": \\("([^"]*)"`)) || [])[1];
  for (const pack of packs) {
    const metric = Object.entries(pack.rules).filter(([, r]) => !(r.output_columns || []).some((c) => ["fault_pct", "fault_hours"].includes(c)));
    assert.deepEqual(metric.map(([id]) => id).sort(), METRIC_IDS);
    for (const [id, r] of metric) {
      const out = hook.resultValue(r, { equipment_id: "VAV-1", [r.output_columns[1]]: 1 });
      assert.equal(out.kind, "metric", id);
      assert.ok(out.unit, `${id} has a unit`);
      assert.equal(out.unit, docUnit(out.column), `${id} ${out.column}`);
      assert.equal(hook.resultValue(r, null).unit, out.unit, `${id}: a not-assessed metric keeps its unit`);
    }
  }
  const p = resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 20.68 });
  assert.equal(p.units, "°C");
  assert.ok(p.tags.includes("metric") && p.tags.includes("fdd") && !p.tags.includes("fault"));
  assert.equal(p.rec.attrs.fddStatus, "ok");
});

test("a METRIC result is a metric with its value and unit, never insufficient or a fault", () => {
  const of = get("fddEntryOf"), text = get("fddMetricText");
  const avg = of(row("AVG-ZONE-TEMP"), resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 20.68 }));
  assert.deepEqual([avg.status, avg.value, avg.unit, avg.reason, avg.faultHours], ["metric", 20.68, "°C", "", null]);
  assert.equal(text(avg, "si"), "20.68 °C");
  assert.equal(text(avg, "imperial"), "69.22 °F");
  const pct = of(row("ZONE-COMFORT-PCT"), resultPoint("ZONE-COMFORT-PCT", { equipment_id: "VAV-1", comfort_pct: 100 }));
  assert.deepEqual([pct.status, text(pct, "imperial")], ["metric", "100 %"]);
  // fan runtime is in hours and > 0: still a metric, not fault hours
  const fan = of(row("FAN-RUNTIME-HOURS"), resultPoint("FAN-RUNTIME-HOURS", { equipment_id: "VAV-1", fan_runtime_hours: 7.5, total_hours: 24 }));
  assert.deepEqual([fan.status, fan.faultHours, text(fan, "imperial")], ["metric", null, "7.5 h"]);
  // 0 is a valid metric value
  assert.equal(of(row("ZONE-COMFORT-PCT"), resultPoint("ZONE-COMFORT-PCT", { equipment_id: "VAV-1", comfort_pct: 0 })).status, "metric");
  // a 5.0.21 point written without a unit gets its output column's unit
  const old = of(row("AVG-ZONE-TEMP"), resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 21 }, { unit: "" }));
  assert.deepEqual([old.status, old.unit, text(old, "imperial")], ["metric", "°C", "69.8 °F"]);
});

test("real insufficient / no-result cases still say so, for metric and fault rules alike", () => {
  const of = get("fddEntryOf");
  const none = of(row("AVG-ZONE-TEMP"), null);
  assert.deepEqual([none.status, none.reason], ["insufficient", "no result written yet"]);
  const na = of(row("AVG-ZONE-TEMP"), resultPoint("AVG-ZONE-TEMP", null));
  assert.equal(na.status, "insufficient");
  assert.match(na.reason, /no row/);
  const stale = resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 20 });
  stale.rec.attrs.fddStatus = "stale";
  assert.deepEqual([of(row("AVG-ZONE-TEMP"), stale).status, of(row("AVG-ZONE-TEMP"), stale).reason], ["insufficient", "input data is stale (no recent samples)"]);
  const empty = of(row("ZONE-COMFORT-PCT"), resultPoint("ZONE-COMFORT-PCT", { equipment_id: "VAV-1", comfort_pct: 50 }, { latest: null }));
  assert.deepEqual([empty.status, empty.reason], ["insufficient", "no value written yet"]);
  assert.equal(of(row("AVG-ZONE-TEMP", { runnable: false, missing: ["zone_air_temperature"] }), null).status, "skipped");
  // fault rules are unchanged
  const fx = (v, attrs) => ({ latest: { double: v }, units: "%", tags: ["point", "his", "fault", "fdd"], rec: { attrs: { fddOutput: "fault_pct", fddWindowHours: "24", ...attrs } } });
  assert.equal(of(row("FC1"), fx(12, { fddStatus: "fault" })).status, "fault");
  assert.equal(of(row("FC1"), fx(0, { fddStatus: "ok" })).status, "pass");
});

test("summary and list: metrics get their own chip, are not counted as insufficient, and sit behind show all", () => {
  const of = get("fddEntryOf");
  const entries = [
    of(row("AVG-ZONE-TEMP"), resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 20.68 })),
    of(row("ZONE-COMFORT-PCT"), resultPoint("ZONE-COMFORT-PCT", { equipment_id: "VAV-1", comfort_pct: 100 })),
    of(row("VAV-1"), null),
  ];
  const s = get("fddSummary")(entries);
  assert.deepEqual([s.metric.count, s.insufficient.count, s.fault.count, s.metric.hours], [2, 1, 0, 0]);
  assert.equal(get("FDD_STATUS_LABELS").metric, "Metrics");
  const vis = get("fddVisibleEntries");
  assert.deepEqual(Array.from(vis(entries, {}).shown, (e) => e.ruleId), ["VAV-1"]);
  assert.equal(vis(entries, {}).hidden, 2);
  assert.deepEqual(Array.from(vis(entries, { filter: "metric" }).shown, (e) => e.ruleId), ["AVG-ZONE-TEMP", "ZONE-COMFORT-PCT"]);
  assert.equal(get("fddUrlState")("?fdd.filter=metric").filter, "metric");
});

test("result lookup: the FDD tab finds a metric point; fault lanes (rcxResultPoint) never use it", () => {
  const p = resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 20.68 });
  const model = { sites: [], equips: [equipRec], devices: [], points: [p] };
  assert.equal(get("rcxRuleResultPoint")(model, equipRec, "AVG-ZONE-TEMP"), p);
  assert.equal(get("rcxResultPoint")(model, equipRec, "AVG-ZONE-TEMP"), null);
  assert.equal(get("rcxRuleResultPoint")(model, equipRec, "ZONE-COMFORT-PCT"), null);
});

test("export: a metric column is named by its output and carries its SI unit", () => {
  const p = resultPoint("AVG-ZONE-TEMP", { equipment_id: "VAV-1", avg_zone_temp: 20.68 });
  const model = { sites: [{ name: "Site A", attrs: { id: site } }], equips: [equipRec], devices: [], points: [{ ...p, siteRef: site, equipRef: "VAV-1" }] };
  const col = X.exportCandidates(model, { site, equip: "VAV-1" }).fddPoints[0];
  assert.equal(col.unit, "°C");
  assert.equal(col.dis, "AVG-ZONE-TEMP · avg_zone_temp");
});
