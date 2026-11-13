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
