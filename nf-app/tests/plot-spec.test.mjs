// Plot spec: the JS producer against the golden files the Python producer is also tested against (byte-identical
// canonical JSON), schema validation, determinism, units.json vs units.js, and the fixture model not drifting.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import { modelJson } from "./fixtures/plot_spec_model.mjs";

const require = createRequire(import.meta.url);
const spec = require("../static/plot-spec.js");
const units = require("../static/units.js");
const root = new URL("../../", import.meta.url);
const read = (rel) => readFileSync(new URL(rel, root), "utf8").replace(/\r\n/g, "\n");
const json = (rel) => JSON.parse(read(rel));
const catalog = json("nf-app/static/fdd-catalog.json");
const model = json("tests/fixtures/plot_spec/model.json");
const cases = json("tests/fixtures/plot_spec/cases.json");
const schema = json("open_fdd/data/plot_spec.schema.json");

const equipOf = (s) => { const [site, id] = s.split("/"); return model.equips.find((e) => e.attrs.siteRef === site && e.attrs.id === id); };
const build = (c) => (c.kind === "rule"
  ? spec.buildRuleSpec(model, c.id, equipOf(c.equips[0]), cases.window, { catalog })
  : spec.buildPresetSpec(model, c.id, c.equips.map(equipOf), cases.window, { catalog }));

/** Minimal JSON Schema (the draft 2020-12 subset the plot-spec schema uses). Returns a list of errors. */
function validate(value, sch, path = "$") {
  const errs = [];
  if (sch.$ref) return validate(value, schema.$defs[sch.$ref.split("/").pop()], path);
  const kind = (v) => (v === null ? "null" : Array.isArray(v) ? "array" : Number.isInteger(v) ? "integer" : typeof v);
  if ("const" in sch && value !== sch.const) errs.push(`${path}: not ${sch.const}`);
  if (sch.enum && !sch.enum.includes(value)) errs.push(`${path}: ${JSON.stringify(value)} not in enum`);
  if (sch.type) {
    const want = [].concat(sch.type), k = kind(value);
    if (!want.some((t) => t === k || (t === "number" && k === "integer"))) { errs.push(`${path}: type ${k}, want ${want}`); return errs; }
  }
  if (typeof value === "string" && sch.pattern && !new RegExp(sch.pattern).test(value)) errs.push(`${path}: pattern`);
  if (typeof value === "number") {
    if (sch.minimum != null && value < sch.minimum) errs.push(`${path}: below minimum`);
    if (sch.maximum != null && value > sch.maximum) errs.push(`${path}: above maximum`);
  }
  if (Array.isArray(value) && sch.items) value.forEach((v, i) => errs.push(...validate(v, sch.items, `${path}[${i}]`)));
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const r of sch.required || []) if (!(r in value)) errs.push(`${path}: missing ${r}`);
    for (const [k, v] of Object.entries(value)) {
      if (sch.properties && sch.properties[k]) errs.push(...validate(v, sch.properties[k], `${path}.${k}`));
      else if (sch.additionalProperties === false) errs.push(`${path}: unexpected ${k}`);
    }
  }
  return errs;
}

test("the committed fixture model matches its generator", () => {
  assert.equal(read("tests/fixtures/plot_spec/model.json"), modelJson());
});

for (const c of cases.cases) {
  test(`golden ${c.name}: byte-identical canonical JSON and schema-valid`, () => {
    const out = build(c);
    assert.deepEqual(validate(out, schema), []);
    assert.equal(spec.toJson(out), read(`tests/fixtures/plot_spec/golden/${c.name}.json`));
    assert.equal(spec.toJson(build(c)), spec.toJson(out), "deterministic");
  });
}

test("the golden cases cover the briefed rules and presets", () => {
  const out = Object.fromEntries(cases.cases.map((c) => [c.name, build(c)]));
  const flow = out["rule-sv-range-chw-flow"];
  const flowSeries = flow.series.find((s) => s.role === "chw_flow");
  assert.ok(flowSeries && flowSeries.quantity === "flow_water" && flowSeries.unit_si === "L/s");
  assert.equal(flow.fault_strips.find((s) => s.sensor_uuid === flowSeries.point_uuid).source, "timeline");
  assert.ok(flow.fault_strips.some((s) => s.source === "intervals" && s.point_uuid === null));
  assert.equal(out["rule-chw-1"].fault_strips[0].source, "fault_pct");
  assert.equal(out["rule-chw-1"].fault_strips[0].approximate, true);
  assert.deepEqual(out["rule-chw-1"].missing, [{ role: "chiller_power", reason: "unit_unusable" }]);
  assert.equal(out["rule-fc1"].fault_strips[0].source, "timeline");
  assert.deepEqual(out["preset-ahu-cooling-valves-unbound-by-alias"].missing, [{ role: "clg_valve_pct", reason: "unbound" }]);
  assert.equal(out["preset-ahu-cooling-valves-unbound-by-alias"].preset_id, "ahu-cooling-valves");
  const dats = out["preset-ahu-dats-imperial-site"];
  assert.ok(dats.series.every((s) => s.unit_si === "°C" && s.quantity === "temperature"));
});

test("color_key: FNV-1a of the uuid, stable, 0-11", () => {
  assert.equal(spec.colorKey(""), 0x811c9dc5 % 12);
  assert.equal(spec.colorKey("a"), 0xe40c292c % 12);   // FNV-1a 32 of "a"
  for (const c of cases.cases) for (const s of build(c).series) assert.equal(s.color_key, spec.colorKey(s.point_uuid));
});

test("never binds across sites (both sites have an AHU-1)", () => {
  const a = spec.buildPresetSpec(model, "ahu_mats", [equipOf("site-a/AHU-1")], cases.window, { catalog });
  const b = spec.buildPresetSpec(model, "ahu_mats", [equipOf("site-b/AHU-1")], cases.window, { catalog });
  assert.equal(a.series.length, 1);
  assert.equal(b.series.length, 1);
  assert.notEqual(a.series[0].point_uuid, b.series[0].point_uuid);
  assert.throws(() => spec.buildPresetSpec(model, "ahu_mats", [equipOf("site-a/AHU-1"), equipOf("site-b/AHU-1")], cases.window, { catalog }), /one site/);
});

test("binding agrees with fdd.js bindRoles on the fixture", () => {
  const vm = require("node:vm");
  const ctx = vm.createContext({ console });
  vm.runInContext(readFileSync(new URL("nf-app/static/fdd.js", root), "utf8") + "\nglobalThis.__bind = bindRoles;", Object.assign(ctx, {
    has: (p, ...m) => m.every((x) => p.tags.includes(x)), markersOf: () => [], idOf: () => "",
  }));
  const a = spec.buildRuleSpec(model, "FC1", equipOf("site-a/AHU-1"), cases.window, { catalog });
  const pool = model.points.filter((p) => p.siteRef === "site-a" && p.equipRef === "AHU-1" && p.tags.includes("point"));
  const bound = ctx.__bind(["duct_static", "duct_static_sp", "fan_cmd", "fan_status"], pool, catalog);
  for (const s of a.series) assert.equal(bound[s.role][0].uuid, s.point_uuid, s.role);
});

test("registry: ids unique, aliases resolve, roles and rules exist", () => {
  const reg = json("open_fdd/data/rcx_presets.json").presets;
  assert.equal(new Set(reg.map((p) => p.id)).size, reg.length);
  for (const [alias, id] of [["ahu_cooling_valves", "ahu-cooling-valves"], ["ahu_heating_valves", "ahu-heating-valves"],
    ["ahu_motor_weekly", "weekly-fan"], ["boiler_motor_weekly", "weekly-pump"], ["chiller_motor_weekly", "weekly-chiller"],
    ["mech_cooling_oat_bins", "mech-cooling-chiller-status"]]) assert.equal(spec.resolvePresetId(alias), id);
  const rules = new Set(catalog.rules.map((r) => r.id));
  for (const p of reg) {
    for (const s of p.series) if (s.role) assert.ok(catalog.roles[s.role], `${p.id}: role ${s.role}`);
    for (const r of p.fault_rules) assert.ok(rules.has(r), `${p.id}: rule ${r}`);
    for (const k of p.equip_kinds) assert.ok(catalog.equipment_kinds[k], `${p.id}: kind ${k}`);
  }
});

test("units.json conversions equal units.js on sample values, for every quantity that units.js has", () => {
  const doc = json("open_fdd/data/units.json"), samples = [-40, -1.5, 0, 0.5, 1, 20, 21.5, 100, 1234.5];
  const close = (a, b) => assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b)), `${a} vs ${b}`);
  for (const [name, q] of Object.entries(doc.quantities)) {
    if (!q.units_js) { assert.ok(q.note, `${name}: no units.js equivalent needs a note`); continue; }
    for (const sys of ["si", "imperial"]) {
      const d = q.display[sys];
      for (const v of samples) {
        const want = q.units_js.fn === "deltaFromSI" ? units.deltaFromSI(v, q.units_js.si, sys) : units.fromSI(v, q.units_js.si, sys);
        close(v * d.mul + d.add, want.value);
        assert.equal(d.unit, want.unit, `${name}/${sys} unit`);
      }
    }
  }
  const siOf = { pressure: "pressure_air", flow: "flow_air" };
  for (const row of doc.aliases.filter((r) => r.units_js)) {
    for (const n of row.names) for (const v of samples) {
      const want = units.toSI(v, n);
      assert.ok(want, `units.js knows ${n}`);
      close(v * row.to_si.mul + row.to_si.add, want.value);
      assert.equal(doc.quantities[siOf[row.quantity] || row.quantity].si, want.unit, `${n} SI unit`);
    }
  }
  for (const n of ["inH2O", "psi", "cfm"]) assert.ok(doc.aliases.some((r) => r.names.includes(n)));
});
