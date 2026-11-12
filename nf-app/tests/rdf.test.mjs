// node --test nf-app/tests/rdf.test.mjs — slice 6: external time-series refs in the Turtle export.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const load = () => {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of ["paging.js", "nf.js", "model.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
};
const rec = (name, attrs) => ({ uuid: `uuid-${name}`, name, pointType: "POINT", attrs });
const model = (ctx) => ({
  sites: [{ uuid: "s", name: "S", pointType: "SITE", attrs: { id: "s" } }],
  equips: [{ uuid: "e", name: "E", pointType: "EQUIPMENT", attrs: { id: "E", siteRef: "s", markers: "equip" } }],
  devices: [],
  points: [
    rec("A", { siteRef: "s", equipRef: "E", markers: "point,sensor,temp,his" }),
    rec("B", { siteRef: "s", equipRef: "E", markers: "point,cmd,fan,his" }),
    rec("X", { siteRef: "s" }),   // untagged: not exported
  ].map(ctx.toPoint),
});

test("every exported point has exactly one NF time-series reference with its uuid", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:", { nfBase: "http://nf.example.test/" });
  assert.equal((turtle.match(/ref:hasExternalReference/g) || []).length, 2);
  for (const u of ["uuid-A", "uuid-B"]) {
    assert.ok(turtle.includes(`ref:hasTimeseriesId "${u}"`), u);
    assert.ok(turtle.includes(`<http://nf.example.test/api/v1/point/data?uuids=${u}>`), `url for ${u}`);
  }
  assert.ok(!turtle.includes("uuid-X"));
  assert.match(turtle, /@prefix ref: <https:\/\/brickschema\.org\/schema\/Brick\/ref#> \./);
});

test("the store node is defined and no TimescaleDB store appears without the option", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:", { nfBase: "http://nf.example.test" });
  assert.match(turtle, /^local:store_nf\n\s+a ref:Database/m);
  assert.ok(!turtle.includes("store_timescaledb"));
  assert.ok(!turtle.includes("http://nf.example.test//"), "no double slash from the base");
});

test("full-profile hook adds a second reference per point and defines the store", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:", { nfBase: "http://nf", timescale: { label: "TSDB" } });
  assert.equal((turtle.match(/ref:storedAt local:store_timescaledb/g) || []).length, 2);
  assert.match(turtle, /^local:store_timescaledb\n\s+a ref:Database/m);
});

test("no page origin and no nfBase: uuid-only reference, no URL, nothing hard-coded", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:");
  assert.ok(turtle.includes('ref:hasTimeseriesId "uuid-A"'));
  assert.ok(!/schema:url <http/.test(turtle));
  assert.ok(!/\d+\.\d+\.\d+\.\d+/.test(turtle));
});

// ---- 5.0.3: site / equip / device subjects are unique across sites -----------------------------------------------------------
// Two sites that both have an `AHU-1` (and a device `CTRL-1`) used to collide on local:AHU-1. Subjects are now the NF
// record uuid (points already were), else a site-prefixed id; refs resolve to those same subjects.
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { twoSite as fx } from "./fixtures/two_site.mjs";

const require = createRequire(import.meta.url);
const sparqlHook = require("../hooks/sparql.js");
const A = fx.sites["site-a"], B = fx.sites["site-b"];
const CHECKER = fileURLToPath(new URL("../../tools/rdf-check/check_ttl.py", import.meta.url));

/** The two-site fixture as a model.js model, plus one device `CTRL-1` per site that its AHU points reference. */
function twoSiteModel(ctx, { uuids = true } = {}) {
  const strip = (r) => (uuids ? r : { ...r, uuid: undefined });
  const dev = (s) => ({ uuid: `dev-${s.id}`, name: "CTRL-1", layer: "model", pointType: "DEVICE", attrs: { id: "CTRL-1", dis: "CTRL-1", markers: "device,controller", siteRef: s.id, equipRef: "AHU-1" } });
  const points = fx.model.points.map((p) => ctx.toPoint({ ...p.rec, attrs: { ...p.rec.attrs, ...(p.equipRef ? { deviceRef: "CTRL-1" } : {}) } }));
  return { sites: fx.model.sites.map(strip), equips: fx.model.equips.map(strip), devices: [A, B].map((s) => strip(dev(s))), points };
}
const ttlOf = (model, ctx) => ctx.modelToTurtle(model, "urn:test:", { nfBase: "http://nf.example.test" }).turtle;
const python = () => ["python", "python3", "py"].find((c) => { const r = spawnSync(c, ["-c", "import rdflib, pyoxigraph"], { encoding: "utf8" }); return r.status === 0; });
const check = (py, ttl) => {
  const file = `${mkdtempSync(`${tmpdir()}/rdf-`)}/m.ttl`;
  writeFileSync(file, ttl);
  return spawnSync(py, [CHECKER, file], { encoding: "utf8" });
};
const sparql = (ttl, q) => sparqlHook.runSparql(ttl, `${ttl.split("\n").filter((l) => l.startsWith("@prefix")).map((l) => l.replace(/^@prefix (\S+) (<[^>]*>) \./, "PREFIX $1 $2")).join("\n")}\n${q}`);

test("two sites with AHU-1: distinct equip subjects (the NF uuids), refs follow, the checker passes", (t) => {
  const ctx = load();
  const ttl = ttlOf(twoSiteModel(ctx), ctx);
  for (const s of [A, B]) {
    assert.equal((ttl.match(new RegExp(`^local:${s.equipUuid}$`, "gm")) || []).length, 1, `${s.id} equip subject`);
    assert.equal((ttl.match(new RegExp(`^local:${s.siteUuid}$`, "gm")) || []).length, 1, `${s.id} site subject`);
    assert.ok(ttl.includes(`local:dev-${s.id}\n`), `${s.id} device subject is its uuid`);
    assert.ok(ttl.includes(`phIoT:siteRef local:${s.siteUuid}`), "siteRef -> the site's own subject");
  }
  assert.ok(!/^local:AHU-1$/m.test(ttl) && !/^local:CTRL-1$/m.test(ttl) && !/^local:site-a$/m.test(ttl), "no bare Haystack-id subjects");
  const rows = sparql(ttl, `SELECT ?e ?label ?siteLabel WHERE { ?e a phIoT:equip ; rdfs:label ?label ; phIoT:siteRef ?s . ?s rdfs:label ?siteLabel }`).rows;
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r[1]), ["AHU-1", "AHU-1"], "the display name is the label");
  assert.equal(new Set(rows.map((r) => r[0])).size, 2, "two distinct AHU-1 subjects");
  assert.deepEqual(rows.map((r) => r[2]).sort(), ["site-a", "site-b"]);
  // every point of an AHU points at ITS site's AHU and ITS site's device (resolved through the model, not by bare id)
  const pts = sparql(ttl, `SELECT ?p ?e ?d WHERE { ?p a phIoT:point ; phIoT:equipRef ?e ; phIct:deviceRef ?d ; phIoT:siteRef ?s . ?e phIoT:siteRef ?s . ?d phIoT:siteRef ?s }`).rows;
  const nPts = twoSiteModel(ctx).points.filter((p) => p.equipRef).length;
  assert.equal(pts.length, nPts, "every AHU point: equip and device are in the point's own site");
  assert.ok(pts.every((r) => [`urn:test:${A.equipUuid}`, `urn:test:${B.equipUuid}`].includes(r[1])));
  const py = python();
  if (!py) return t.skip("python with rdflib + pyoxigraph not available");
  const r = check(py, ttl);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /no problems/);
});

test("without NF uuids the subject is the site-prefixed id (two AHU-1 stay distinct); refs still resolve", (t) => {
  const ctx = load();
  const ttl = ttlOf(twoSiteModel(ctx, { uuids: false }), ctx);
  for (const id of ["site-a_AHU-1", "site-b_AHU-1", "site-a_CTRL-1", "site-b_CTRL-1", "site-a", "site-b"]) {
    assert.equal((ttl.match(new RegExp(`^local:${id}$`, "gm")) || []).length, 1, id);
  }
  assert.ok(ttl.includes("phIoT:equipRef local:site-a_AHU-1") && ttl.includes("phIoT:equipRef local:site-b_AHU-1"));
  assert.ok(ttl.includes("phIct:deviceRef local:site-b_CTRL-1"));
  const py = python();
  if (!py) return t.skip("python with rdflib + pyoxigraph not available");
  const r = check(py, ttl);
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("a ref whose target is not in the model keeps the old local:<id> form and the checker flags it", (t) => {
  const ctx = load();
  const model = twoSiteModel(ctx);
  model.points.push(ctx.toPoint({ uuid: "ghost-pt", name: "GHOST", layer: "default", pointType: "POINT", attrs: { siteRef: "site-a", equipRef: "GHOST-9", markers: "point,sensor,temp,his", kind: "Number", dis: "ghost" } }));
  const ttl = ttlOf(model, ctx);
  assert.ok(ttl.includes("phIoT:equipRef local:GHOST-9"), "unknown target: old behaviour");
  const py = python();
  if (!py) return t.skip("python with rdflib + pyoxigraph not available");
  const r = check(py, ttl);
  assert.equal(r.status, 1);
  assert.match(r.stdout, /dangling ref: .*GHOST-9/);
});

test("the SPARQL examples still return rows on the two-site model", () => {
  const ctx = load();
  const ttl = ttlOf(twoSiteModel(ctx), ctx);
  const lib = require("../static/sparql.js");
  const ex = Object.fromEntries(lib.sparqlExamples(ttl).map((e) => [e.id, e.query]));
  const run = (id) => sparqlHook.runSparql(ttl, ex[id]);
  assert.ok(run("ts-ids").rows.length > 10);
  assert.ok(run("ts-refs").rows.length > 10);
  assert.ok(run("counts").rows.length > 5);
  const kinds = run("equips-kinds");
  assert.deepEqual(kinds.vars, ["site", "equip", "kind", "points"]);
  assert.deepEqual([...new Set(kinds.rows.map((r) => r[0]))].sort(), ["site-a", "site-b"], "two AHU-1 are two groups, not merged");
  for (const id of ["faults", "no-equip"]) assert.ok(Array.isArray(run(id).rows), id);
  // the fault example finds a result point of site-b's AHU-1 without mixing in site-a's
  const m = twoSiteModel(ctx);
  m.points.push(ctx.toPoint({ uuid: "res-b", name: "CMD-1", layer: "default", pointType: "POINT", attrs: { siteRef: "site-b", equipRef: "AHU-1", markers: "point,his,fdd,fault", ruleRef: "CMD-1", dis: "CMD-1 fault" } }));
  const fr = sparqlHook.runSparql(ttlOf(m, ctx), lib.sparqlExamples(ttlOf(m, ctx)).find((e) => e.id === "faults").query);
  assert.equal(fr.rows.length, 1);
});

test("lite/static/model.js has the identical modelToTurtle", () => {
  const body = (f) => { const s = readFileSync(new URL(f, import.meta.url), "utf8").replace(/\r\n/g, "\n"); return s.slice(s.indexOf("function modelToTurtle(")); };
  assert.equal(body("../../lite/static/model.js"), body("../static/model.js"));
});
