// node --test nf-app/tests/rdf-base.test.mjs — #1773: one base IRI for one model, whatever host it was read through.
// The UI (Model & RDF tab, SPARQL tab), the rdf hook (Full and Lite), the sparql hook and the sparql-data hook must give
// the same subjects; before, the UI used location.host and the hooks sdk.http's baseURL.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const rdfFull = require("../hooks/rdf.js");
const rdfLite = require("../../lite/hooks/rdf.js");
const sparqlHook = require("../hooks/sparql.js");
const sparqlData = require("../hooks/sparql_data.js");

const fixture = JSON.parse(readFileSync(new URL("../../tools/rdf-check/fixtures/model.json", import.meta.url), "utf8"));
const SITE = "11111111-0000-4000-8000-000000000001";
const SAT = "11111111-0000-4000-8000-000000000004";
const HOSTS = ["http://127.0.0.1:8090", "http://192.168.1.50:8090", "https://nf-proxy.example.test", "http://100.64.0.7:8080/"];

/** Mock NF on `baseURL`: point/query from the fixture. */
const sdkOn = (baseURL, records = fixture.records) => {
  const model = records.filter((r) => r.pointType !== "POINT");
  const pts = records.filter((r) => r.pointType === "POINT");
  const http = {
    defaults: { baseURL },
    post: async (_url, body) => ({ data: { points: body.layer === "model" ? model : pts, totalCount: (body.layer === "model" ? model : pts).length } }),
  };
  return { http, logEvent: () => {} };
};

/** The page's static/model.js under a browser `location` of `host`, as app-core.js / sparql.js call it. */
const uiTurtle = (app, host, records = fixture.records) => {
  const loc = new URL(`http://${host}/api/v1/apps/static/open-fdd/`);
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa, location: loc });
  vm.runInContext(readFileSync(new URL(`../../${app}/static/model.js`, import.meta.url), "utf8"), ctx, { filename: "model.js" });
  const get = (n) => vm.runInContext(n, ctx);
  const toPoint = get("toPoint"), ENTITY_TYPES = get("ENTITY_TYPES");
  const of = (t) => records.filter((r) => r.pointType === t);
  const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: of("DEVICE"),
    points: records.filter((r) => !ENTITY_TYPES.includes(r.pointType)).map(toPoint) };
  // nfBase "" as the hooks default: only the subjects (not the schema:url history links) are compared by host
  const base = get("rdfBaseOf")(model);
  return { base, turtle: get("modelToTurtle")(model, base, { nfBase: "" }).turtle };
};

const subjects = (ttl) => [...ttl.matchAll(/^(local:\S+)$/gm)].map((m) => m[1]).sort();

test("the UI calls rdfBaseOf(model), never location.host, for the Turtle base", () => {
  for (const f of ["shared/static/app-core.js", "nf-app/static/app-core.js", "lite/static/app-core.js", "nf-app/static/sparql.js"]) {
    const src = readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
    assert.ok(!/modelToTurtle\([^)]*location\.host/.test(src), `${f} builds the base from location.host`);
    assert.match(src, /modelToTurtle\(model, rdfBaseOf\(model\)\)/, f);
  }
});

test("rdfBaseOf: from the site uuid, order-independent, no host", () => {
  const { base } = uiTurtle("nf-app", "10.0.0.9:8090");
  assert.equal(base, `urn:nf:site:${SITE}:`);
  const ctx = vm.createContext({});
  vm.runInContext(readFileSync(new URL("../static/model.js", import.meta.url), "utf8"), ctx);
  const of = vm.runInContext("rdfBaseOf", ctx);
  const a = { uuid: "bbbb", attrs: { id: "a" } }, b = { uuid: "aaaa", attrs: { id: "b" } };
  assert.equal(of({ sites: [a, b] }), "urn:nf:site:aaaa:");
  assert.equal(of({ sites: [b, a] }), "urn:nf:site:aaaa:");
  assert.equal(of({ sites: [{ name: "S 1", attrs: { id: "site one" } }] }), "urn:nf:site:site_one:");
  assert.equal(of({ sites: [] }), "urn:nf:");
});

test("UI and rdf hook (Full and Lite): byte-identical Turtle whatever host or baseURL", async () => {
  const ui = HOSTS.map((h) => uiTurtle("nf-app", new URL(h).host));
  const uiLite = HOSTS.map((h) => uiTurtle("lite", new URL(h).host));
  for (const u of [...ui, ...uiLite]) assert.equal(u.turtle, ui[0].turtle);
  for (const hook of [rdfFull, rdfLite]) {
    for (const h of HOSTS) {
      const r = await hook.handle({ sdk: sdkOn(h), args: { limit: "190000" } });
      assert.equal(r.ok, true, JSON.stringify(r));
      assert.equal(r.next_offset, null);
      assert.equal(r.base, ui[0].base, h);
      assert.equal(r.turtle, ui[0].turtle, `rdf hook on ${h}`);
      assert.ok(!r.turtle.includes("127.0.0.1") && !r.turtle.includes("192.168."), "no host in the Turtle");
    }
  }
  assert.ok(subjects(ui[0].turtle).includes(`local:${SAT}`));
});

test("rdf hook: args.base still overrides", async () => {
  const r = await rdfFull.handle({ sdk: sdkOn(HOSTS[0]), args: { base: "urn:custom:" } });
  assert.equal(r.base, "urn:custom:");
  assert.match(r.turtle, /@prefix local: <urn:custom:> \./);
});

test("sparql hook: same base and subjects as the UI whatever baseURL", async () => {
  const want = uiTurtle("nf-app", "192.168.1.50:8090").base;
  const q = "SELECT ?p WHERE { ?p a <https://project-haystack.org/def/phIoT/point> } ORDER BY ?p";
  const seen = [];
  for (const h of HOSTS) {
    const r = await sparqlHook.handle({ sdk: sdkOn(h), args: { query: q, format: "json" } });
    assert.equal(r.ok, true, JSON.stringify(r));
    assert.equal(r.base, want, h);
    seen.push(JSON.stringify(r.rows));
  }
  assert.equal(new Set(seen).size, 1, "rows differ by host");
  assert.ok(seen[0].includes(`${want}${SAT}`), seen[0]);
});

test("sparql-data: point IRIs in the new base and older host-based IRIs both name the point", () => {
  const points = [{ uuid: SAT }];
  const base = `urn:nf:site:${SITE}:`;
  assert.deepEqual(sparqlData.pickPoints(["p"], [[`${base}${SAT}`]], points, base).uuids, [SAT]);
  assert.deepEqual(sparqlData.pickPoints(["p"], [[`urn:nf:192.168.1.50:8090:${SAT}`]], points, base).uuids, [SAT]);
  assert.throws(() => sparqlData.pickPoints(["p"], [["urn:nf:192.168.1.50:8090:not-a-point"]], points, base), /names no point/);
  assert.throws(() => sparqlData.pickPoints(["p"], [[`http://x.test/${SAT}`]], points, base), /names no point/);
});
