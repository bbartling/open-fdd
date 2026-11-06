// Regression tests for GitHub #1537 and #1538, re-stated for the 5.0 NF app.
// In 4.x both bugs lived in central analytics SQL (setpoints_snapshot.sql, topology_equipment.sql),
// which is retired. In 5.0 the same jobs — "which point is a setpoint for role X" and "which
// points belong to which equipment" — are done by static/fdd.js role binding over NF's Haystack
// model. These tests pin that the binding cannot reproduce either bug:
//   #1537: no name/suffix wildcard — a measured duct static pressure (or a point merely *named*
//          like a setpoint) never fills a setpoint role; only tags/NF class decide.
//   #1538: no parsing of opaque keys — equipment membership comes only from the point's current
//          equipRef/siteRef binding, whatever its uuid/name syntax.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const ctx = vm.createContext({ console });
for (const f of ["model.js", "fdd.js"]) vm.runInContext(fs.readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
const get = (n) => vm.runInContext(n, ctx);
const catalog = JSON.parse(fs.readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
const toPoint = get("toPoint");

const pt = (uuid, name, markers, attrs = {}) => toPoint({ uuid, name, pointType: "POINT",
  attrs: { markers: ["point", "his", ...markers].join(","), siteRef: "site-a", dis: name, ...attrs } });
const equip = (id, markers, site = "site-a") => ({ uuid: `e-${id}`, name: id, pointType: "EQUIPMENT", attrs: { id, siteRef: site, markers } });
const bound = (rows, ruleRoleOwner, role) => {
  const r = rows.find((x) => x.bound[role]);
  return r ? Array.from(r.bound[role], (p) => p.uuid) : [];
};
const rolesOf = (equipRec, model) => {
  const rows = get("equipRules")(equipRec, model, catalog);
  const out = {};
  for (const r of rows) for (const [role, pts] of Object.entries(r.bound)) out[role] = Array.from(pts, (p) => p.uuid);
  return { rows, out };
};

test("#1537: measured duct static pressure never fills the duct static setpoint role", () => {
  const ahu = equip("AHU-1", "equip,ahu");
  const model = { sites: [], equips: [ahu], devices: [], points: [
    // measured DSP: class + markers of a sensor
    pt("u-dsp", "AHU-1 DSP", ["discharge", "air", "pressure", "sensor"], { equipRef: "AHU-1", class: "discharge-air-pressure-sensor" }),
    // named like a setpoint ("xsetpoint", "dsp_sp") but tagged as a sensor -> must not be a setpoint
    pt("u-bogus", "AHU-1 xsetpoint", ["discharge", "air", "pressure", "sensor"], { equipRef: "AHU-1" }),
    // the real setpoint (tags) and a second legit setpoint point sharing the role
    pt("u-dsp-sp", "AHU-1 DSP SP", ["discharge", "air", "pressure", "sp"], { equipRef: "AHU-1", class: "discharge-air-pressure-sp" }),
    pt("u-dsp-sp2", "AHU-1 static_sp", ["discharge", "air", "pressure", "sp"], { equipRef: "AHU-1" }),
    // a setpoint on another site / equip must never leak in
    pt("u-foreign", "AHU-9 DSP SP", ["discharge", "air", "pressure", "sp"], { equipRef: "AHU-9", siteRef: "site-b" }),
  ] };
  const { out } = rolesOf(ahu, model);
  assert.deepEqual(out.duct_static_sp, ["u-dsp-sp", "u-dsp-sp2"], "only tagged setpoints, class match first");
  assert.ok(!out.duct_static_sp.includes("u-dsp") && !out.duct_static_sp.includes("u-bogus"));
  assert.ok(!out.duct_static_sp.includes("u-foreign"));
  assert.equal(out.duct_static[0], "u-dsp", "the measured DSP is the duct static sensor");
});

test("#1537: names never decide a role — tags do", () => {
  const ahu = equip("AHU-1", "equip,ahu");
  const model = { sites: [], equips: [ahu], devices: [], points: [
    pt("u-sat-named-sp", "SAT_SP", ["discharge", "air", "temp", "sensor"], { equipRef: "AHU-1" }),
    pt("u-sat-sp", "whatever", ["discharge", "air", "temp", "sp"], { equipRef: "AHU-1" }),
  ] };
  const { out } = rolesOf(ahu, model);
  assert.deepEqual(out.sat_sp, ["u-sat-sp"]);
  assert.deepEqual(out.sat, ["u-sat-named-sp"]);
});

test("#1538: equipment membership comes from the current equipRef binding, not key syntax", () => {
  const a = equip("AHU-1", "equip,ahu");
  const b = equip("AHU.2", "equip,ahu");   // dotted equip id
  const model = { sites: [], equips: [a, b], devices: [], points: [
    // URI-like / dotted / opaque uuids and names that "look like" another equip
    pt("urn:nf:AHU.2:sat", "AHU.2 SAT", ["discharge", "air", "temp", "sensor"], { equipRef: "AHU-1" }),
    pt("AHU-1.sat.x", "AHU-1 SAT", ["discharge", "air", "temp", "sensor"], { equipRef: "AHU.2" }),
    // two keys, one role, same equip
    pt("k1", "MAT A", ["mixed", "air", "temp", "sensor"], { equipRef: "AHU-1" }),
    pt("k2", "MAT B", ["mixed", "air", "temp", "sensor"], { equipRef: "AHU-1" }),
    // wrong site with the right equip id
    pt("k-wrong-site", "OAT", ["outside", "air", "temp", "sensor"], { equipRef: "AHU-1", siteRef: "site-b" }),
  ] };
  const ra = rolesOf(a, model).out, rb = rolesOf(b, model).out;
  assert.deepEqual(ra.sat, ["urn:nf:AHU.2:sat"], "bound by equipRef, not by the key's text");
  assert.deepEqual(rb.sat, ["AHU-1.sat.x"]);
  assert.deepEqual([...ra.mat].sort(), ["k1", "k2"], "two keys share one role");
  assert.ok(!(ra.oa_t || []).includes("k-wrong-site"), "other site's point never binds");
});

test("#1538: an equip with no points is still listed, with what it is missing", () => {
  const empty = equip("AHU-EMPTY", "equip,ahu");
  const { rows } = rolesOf(empty, { sites: [], equips: [empty], devices: [], points: [] });
  assert.ok(rows.length > 0, "rules still listed for the empty equip");
  assert.ok(rows.every((r) => !r.runnable));
  assert.ok(rows.some((r) => r.missing.length > 0));
});

test("#1538: reassigning a point (equipRef change) moves it", () => {
  const a = equip("AHU-1", "equip,ahu"), b = equip("AHU-2", "equip,ahu");
  const p = pt("u-move", "SAT", ["discharge", "air", "temp", "sensor"], { equipRef: "AHU-1" });
  const model = { sites: [], equips: [a, b], devices: [], points: [p] };
  assert.deepEqual(rolesOf(a, model).out.sat, ["u-move"]);
  p.equipRef = "AHU-2";
  assert.equal((rolesOf(a, model).out.sat || []).length, 0);
  assert.deepEqual(rolesOf(b, model).out.sat, ["u-move"]);
});
