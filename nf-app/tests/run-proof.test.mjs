// Run-proof resolution (#1608): own status, own command, the feeding equipment (airRef / chilledWaterRef / hotWaterRef /
// brick:isFedBy / brick:feeds), none. Synthetic model: tests/fixtures/run_proof_model.json (shared with the Python twin).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const records = JSON.parse(fs.readFileSync(new URL("../../tests/fixtures/run_proof_model.json", import.meta.url), "utf8")).records;
const catalog = JSON.parse(fs.readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
for (const f of ["paging.js", "nf.js", "model.js", "fdd.js", "run-proof.js"]) vm.runInContext(fs.readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
ctx.records = records;
ctx.catalog = catalog;
const resolveAll = () => vm.runInContext(`(() => {
  const of = (t) => records.filter((x) => x.pointType === t);
  const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: [], points: of("POINT").map(toPoint) };
  const out = {};
  for (const e of model.equips) {
    const r = resolveRunProof(e, model, catalog);
    out[(e.attrs.siteRef) + "/" + idOf(e)] = r.found ? { tier: r.tier, source: r.source, role: r.role, equip: r.equip, via: r.via, point: r.point.name } : { found: false, reason: r.reason };
  }
  return JSON.parse(JSON.stringify(out));
})()`, ctx);
const got = JSON.parse(JSON.stringify(resolveAll()));

test("an AHU proves itself by its own fan status, status before command", () => {
  assert.deepEqual({ ...got["s1/AHU-1"], point: undefined }, { tier: "own", source: "status", role: "fan_status", equip: "AHU-1", via: "self", point: undefined });
});

test("with no status the own command is the proof", () => {
  assert.equal(got["s1/AHU-2"].tier, "own");
  assert.equal(got["s1/AHU-2"].source, "command");
  assert.equal(got["s1/AHU-2"].role, "fan_cmd");
});

test("a VAV follows airRef to the AHU fan (with and without the @)", () => {
  assert.deepEqual([got["s1/VAV-1"].tier, got["s1/VAV-1"].equip, got["s1/VAV-1"].via, got["s1/VAV-1"].role], ["feeder", "AHU-1", "airRef", "fan_status"]);
  assert.deepEqual([got["s1/VAV-2"].tier, got["s1/VAV-2"].equip, got["s1/VAV-2"].via, got["s1/VAV-2"].role], ["feeder", "AHU-2", "airRef", "fan_cmd"]);
});

test("a chilled-water loop follows chilledWaterRef, brick:isFedBy and brick:feeds to its pump", () => {
  assert.deepEqual([got["s1/CHW-LOOP-A"].equip, got["s1/CHW-LOOP-A"].via], ["CHWP-1", "chilledWaterRef"]);
  assert.deepEqual([got["s1/CHW-LOOP-C"].equip, got["s1/CHW-LOOP-C"].via], ["CHWP-1", "isFedBy"]);
  assert.deepEqual([got["s1/CHW-LOOP-B"].equip, got["s1/CHW-LOOP-B"].via], ["CHWP-B", "feeds"]);
  assert.equal(got["s1/CHW-LOOP-A"].source, "status");
});

test("a hot-water loop follows hotWaterRef", () => {
  assert.deepEqual([got["s1/HW-LOOP"].equip, got["s1/HW-LOOP"].via], ["HWP-1", "hotWaterRef"]);
});

test("no proof anywhere: not found, reason no_run_proof (never a guess, never across sites)", () => {
  for (const id of ["s1/AHU-3", "s1/VAV-3", "s1/VAV-4", "s1/CHW-LOOP-D", "s2/VAV-9"]) {
    assert.deepEqual(got[id], { found: false, reason: "no_run_proof" }, id);
  }
});

test("the catalog marks every rule gated or exempt, and every exempt rule says why", () => {
  assert.ok(catalog.rules.length > 0);
  for (const r of catalog.rules) {
    assert.ok(r.run_proof === "gated" || r.run_proof === "exempt", r.id);
    if (r.run_proof === "exempt") assert.ok(r.run_proof_note, `${r.id} needs a run_proof_note`);
    else assert.ok(r.optional_roles.includes("run_proof"), `${r.id} must list run_proof`);
  }
});

test("the Turtle export carries the refs and feeds the resolution follows", () => {
  const ttl = vm.runInContext(`(() => {
    const of = (t) => records.filter((x) => x.pointType === t);
    const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: [], points: of("POINT").map(toPoint) };
    return modelToTurtle(model, "urn:test:", { nfBase: "" }).turtle;
  })()`, ctx);
  assert.match(ttl, /phIoT:airRef local:/);
  assert.match(ttl, /phIoT:chilledWaterRef local:/);
  assert.match(ttl, /phIoT:hotWaterRef local:/);
  assert.match(ttl, /brick:isFedBy local:/);
  assert.match(ttl, /brick:feeds local:/);
  assert.match(ttl, /@prefix brick: </);
});

test("ambiguous feeder names bind nothing rather than picking the first equipment", () => {
  const result = vm.runInContext(`(() => {
    const e = { uuid: 'v', name: 'V', attrs: { id: 'V', siteRef: 's1', airRef: 'shared' } };
    const a = { uuid: 'a', name: 'shared', attrs: { id: 'A', siteRef: 's1' } };
    const b = { uuid: 'b', name: 'shared', attrs: { id: 'B', siteRef: 's1' } };
    return runProofFeeders(e, { equips: [e, a, b] }, catalog).length;
  })()`, ctx);
  assert.equal(result, 0);
});

test("a Turtle ref written as the feeder's display name points at the feeder's subject", () => {
  const ttl = vm.runInContext(`(() => {
    const site = { uuid: "s", name: "Site", pointType: "SITE", attrs: { id: "s1" } };
    const ahu = { uuid: "a", name: "Main AHU", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "s1" } };
    const vav = { uuid: "v", name: "VAV", pointType: "EQUIPMENT", attrs: { id: "VAV-1", siteRef: "s1", airRef: "Main AHU" } };
    return modelToTurtle({ sites: [site], equips: [ahu, vav], devices: [], points: [] }, "urn:test:", { nfBase: "" }).turtle;
  })()`, ctx);
  assert.match(ttl, /phIoT:airRef local:a \./, ttl);
});

test("a Turtle ref written as the feeder's dis points at the feeder's subject", () => {
  const ttl = vm.runInContext(`(() => {
    const site = { uuid: "s", name: "Site", pointType: "SITE", attrs: { id: "s1" } };
    const ahu = { uuid: "u1", name: "u1", pointType: "EQUIPMENT", attrs: { siteRef: "s1", dis: "Main Floor AHU" } };
    const vav = { uuid: "v", name: "VAV", pointType: "EQUIPMENT", attrs: { id: "VAV-1", siteRef: "s1", airRef: "Main Floor AHU" } };
    return modelToTurtle({ sites: [site], equips: [ahu, vav], devices: [], points: [] }, "urn:test:", { nfBase: "" }).turtle;
  })()`, ctx);
  assert.doesNotMatch(ttl, /Main_Floor_AHU/, ttl);
  assert.match(ttl, /phIoT:airRef local:u1 \./, ttl);
});

test("a display-name ref is scoped to the referrer's site before an id at another site can win", () => {
  const ttl = vm.runInContext(`(() => {
    const s1 = { uuid: "s", name: "Site", pointType: "SITE", attrs: { id: "s1" } };
    const s2 = { uuid: "t", name: "Other", pointType: "SITE", attrs: { id: "s2" } };
    const ahu = { uuid: "u1", name: "u1", pointType: "EQUIPMENT", attrs: { siteRef: "s1", dis: "Main AHU" } };
    const far = { uuid: "u2", name: "Main AHU", pointType: "EQUIPMENT", attrs: { id: "Main AHU", siteRef: "s2" } };
    const vav = { uuid: "v", name: "VAV", pointType: "EQUIPMENT", attrs: { id: "VAV-1", siteRef: "s1", airRef: "Main AHU" } };
    return modelToTurtle({ sites: [s1, s2], equips: [ahu, far, vav], devices: [], points: [] }, "urn:test:", { nfBase: "" }).turtle;
  })()`, ctx);
  assert.match(ttl, /phIoT:airRef local:u1 \./, ttl);
});

test("a ref matching one record's id and another's name at the same site binds nothing, as in the resolver", () => {
  const ttl = vm.runInContext(`(() => {
    const site = { uuid: "s", name: "Site", pointType: "SITE", attrs: { id: "s1" } };
    const a = { uuid: "a", name: "A", pointType: "EQUIPMENT", attrs: { id: "X", siteRef: "s1" } };
    const b = { uuid: "b", name: "B", pointType: "EQUIPMENT", attrs: { id: "B", siteRef: "s1", dis: "X" } };
    const vav = { uuid: "v", name: "VAV", pointType: "EQUIPMENT", attrs: { id: "VAV-1", siteRef: "s1", airRef: "X" } };
    return modelToTurtle({ sites: [site], equips: [a, b, vav], devices: [], points: [] }, "urn:test:", { nfBase: "" }).turtle;
  })()`, ctx);
  assert.doesNotMatch(ttl, /phIoT:airRef local:(a|b) \./, ttl);
  const nf = vm.runInContext(`(() => {
    const a = { uuid: "a", name: "A", pointType: "EQUIPMENT", attrs: { id: "X", siteRef: "s1" } };
    const b = { uuid: "b", name: "B", pointType: "EQUIPMENT", attrs: { id: "B", siteRef: "s1", dis: "X" } };
    const vav = { uuid: "v", name: "VAV", pointType: "EQUIPMENT", attrs: { id: "VAV-1", siteRef: "s1", airRef: "X" } };
    return resolveRunProof(vav, { sites: [], equips: [a, b, vav], devices: [], points: [] }, catalog).found;
  })()`, ctx);
  assert.equal(nf, false);
});

test("collision fixture: a ref matching one id and another's dis binds nothing, though both have proof", () => {
  const recs = JSON.parse(fs.readFileSync(new URL("../../tests/fixtures/run_proof_collision.json", import.meta.url), "utf8")).records;
  ctx.collision = recs;
  const got = vm.runInContext(`(() => {
    const of = (t) => collision.filter((x) => x.pointType === t);
    const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: [], points: of("POINT").map(toPoint) };
    const r = (id) => resolveRunProof(model.equips.find((e) => idOf(e) === id), model, catalog);
    return { v1: r("VAV-1").found, v2: r("VAV-2").found, v2equip: r("VAV-2").equip,
      ttl: modelToTurtle(model, "urn:test:", { nfBase: "" }).turtle };
  })()`, ctx);
  assert.equal(got.v1, false);
  assert.equal(got.v2, true);   // control: the proof points are real
  assert.equal(got.v2equip, "B");
  assert.doesNotMatch(got.ttl, /local:v1[^.]*phIoT:airRef local:c0000000/);
});

