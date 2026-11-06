// node --test nf-app/tests/sparql.test.mjs — SPARQL helpers (static/sparql.js) + the sparql hook.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const dir = new URL("../static/", import.meta.url);
const hook = require("../hooks/sparql.js");
const lib = require("../static/sparql.js");
const ox = require("../static/vendor/oxigraph/node.js");

const fixture = JSON.parse(readFileSync(new URL("../../tools/rdf-check/fixtures/model.json", import.meta.url), "utf8"));
// The fixture has no fault result point; add one (as the FDD hook writes them).
const records = [...fixture.records, {
  uuid: "22222222-0000-4000-8000-000000000001", name: "fault-AHU-1-sat", pointType: "POINT",
  attrs: { siteRef: "site-a", equipRef: "AHU-1", markers: "point,fault,fdd,his", ruleRef: "sat-low", kind: "Number", dis: "SAT low fault" },
}];

function turtleOf(recs, nfBase = "http://nf.example.test") {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of ["nf.js", "model.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  ctx.records = recs;
  return vm.runInContext(`(() => {
    const of = (t) => records.filter((x) => x.pointType === t);
    const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: of("DEVICE"), points: of("POINT").map(toPoint) };
    return modelToTurtle(model, "urn:test:", { nfBase: ${JSON.stringify(nfBase)} }).turtle;
  })()`, ctx);
}
const TTL = turtleOf(records);

test("prefixes are taken from the Turtle", () => {
  const p = lib.sparqlPrefixes(TTL);
  for (const x of ["PREFIX ph:", "PREFIX phIoT:", "PREFIX ref:", "PREFIX local: <urn:test:>"]) assert.ok(p.includes(x), x);
});

test("every example query runs on the fixture and returns at least one row", () => {
  const examples = lib.sparqlExamples(TTL);
  assert.ok(examples.length >= 5 && examples.length <= 6);
  for (const ex of examples) {
    const r = hook.runSparql(TTL, ex.query, "json", { ox });
    assert.equal(r.kind, "select", ex.id);
    assert.ok(r.rows.length >= 1, `${ex.id} returned no rows`);
  }
});

test("default example lists points with their time-series id and history URL", () => {
  const ex = lib.sparqlExamples(TTL)[0];
  const r = hook.runSparql(TTL, ex.query, "json", { ox });
  assert.deepEqual(r.vars, ["equip", "point", "tsId", "history"]);
  const sat = r.rows.find((row) => row[1] === "Supply air temp");
  assert.ok(sat, "SAT row");
  assert.equal(sat[2], "11111111-0000-4000-8000-000000000004");
  assert.equal(sat[3], "http://nf.example.test/api/v1/point/data?uuids=11111111-0000-4000-8000-000000000004");
});

test("no-equip example finds the weather point only; fault example finds the result point", () => {
  const ex = Object.fromEntries(lib.sparqlExamples(TTL).map((e) => [e.id, e]));
  const none = hook.runSparql(TTL, ex["no-equip"].query, "json", { ox });
  assert.deepEqual(none.rows.map((r) => r[0]), ["WX"]);
  const faults = hook.runSparql(TTL, ex.faults.query, "json", { ox });
  assert.deepEqual(faults.rows.map((r) => r[0]), ["SAT low fault"]);
});

test("ASK, CONSTRUCT and the turtle format", () => {
  const P = lib.sparqlPrefixes(TTL);
  const ask = hook.runSparql(TTL, `${P}\nASK { ?p a phIoT:point }`, "json", { ox });
  assert.deepEqual(ask, { format: "json", kind: "ask", value: true });
  const q = `${P}\nCONSTRUCT { ?p rdfs:label ?l } WHERE { ?p a phIoT:point ; rdfs:label ?l }`;
  const g = hook.runSparql(TTL, q, "turtle", { ox });
  assert.equal(g.kind, "graph");
  assert.equal(g.total, 6);
  assert.match(g.body, /Supply air temp/);
  const gcsv = hook.runSparql(TTL, q, "csv", { ox });
  assert.match(gcsv.body, /^subject,predicate,object\r\n/);
  assert.throws(() => hook.runSparql(TTL, `${P}\nSELECT * WHERE { ?s ?p ?o } LIMIT 1`, "turtle", { ox }), /CONSTRUCT or DESCRIBE/);
});

test("empty SELECT keeps its column names; the row cap truncates", () => {
  const P = lib.sparqlPrefixes(TTL);
  const none = hook.runSparql(TTL, `${P}\nSELECT ?a ?b WHERE { ?a a phIoT:nothing ; rdfs:label ?b }`, "json", { ox });
  assert.deepEqual(none.vars, ["a", "b"]);
  assert.equal(none.rows.length, 0);
  const capped = hook.runSparql(TTL, `SELECT ?s WHERE { ?s ?p ?o }`, "json", { ox, cap: 3 });
  assert.equal(capped.rows.length, 3);
  assert.equal(capped.truncated, true);
  assert.ok(capped.total > 3);
});

test("errors: parse error, bad format, empty query", () => {
  assert.throws(() => hook.runSparql(TTL, "SELEC nope", "json", { ox }));
  assert.throws(() => hook.runSparql(TTL, "ASK {}", "xml", { ox }), /format must be/);
  assert.throws(() => hook.runSparql(TTL, "  ", "json", { ox }), /query is required/);
});

test("CSV escaping: commas, quotes, newlines, unbound", () => {
  assert.equal(lib.sparqlCsvField('a,b'), '"a,b"');
  assert.equal(lib.sparqlCsvField('say "hi"'), '"say ""hi"""');
  assert.equal(lib.sparqlCsvField("l1\nl2"), '"l1\nl2"');
  assert.equal(lib.sparqlCsvField("plain"), "plain");
  assert.equal(lib.sparqlCsvField(null), "");
  const csv = lib.sparqlToCsv({ kind: "select", vars: ["a", "b"], rows: [['x,"y"', null], ["1", "2"]] });
  assert.equal(csv, 'a,b\r\n"x,""y""",\r\n1,2\r\n');
  assert.equal(lib.sparqlToCsv({ kind: "ask", value: false }), "result\r\nfalse\r\n");
});

test("CSV through the real engine escapes a label with a comma and a quote", () => {
  const recs = [...records, { uuid: "33333333-0000-4000-8000-000000000001", name: "Q", pointType: "POINT",
    attrs: { siteRef: "site-a", equipRef: "AHU-1", markers: "point,sensor,temp,his", dis: 'Zone "A", north' } }];
  const ttl = turtleOf(recs);
  const r = hook.runSparql(ttl, `${lib.sparqlPrefixes(ttl)}\nSELECT ?l WHERE { ?p rdfs:label ?l . FILTER(CONTAINS(?l, "north")) }`, "csv", { ox });
  assert.equal(r.body, 'l\r\n"Zone ""A"", north"\r\n');
});

test("hook handle(): loads the model through sdk.http, logs and returns the answer", async () => {
  const model = records.filter((r) => r.pointType !== "POINT");
  const pts = records.filter((r) => r.pointType === "POINT").map((r) => ({ ...r, layer: "default" }));
  const http = {
    post: async (url, body) => ({ data: { points: body.layer === "model" ? model : pts } }),
    defaults: { baseURL: "http://127.0.0.1:8080" },
  };
  const logs = [];
  const sdk = { http, logEvent: (m) => logs.push(m) };
  const out = await hook.handle({ sdk, args: { query: "SELECT (COUNT(*) AS ?n) WHERE { ?p a <https://project-haystack.org/def/phIoT/point> }", format: "json" } });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.rows[0][0], String(records.filter((r) => r.pointType === "POINT" && r.attrs.markers).length));
  assert.equal(logs.length, 1);
  assert.equal(JSON.parse(logs[0]).ok, true);
  const bad = await hook.handle({ sdk, args: { query: "SELEC" } });
  assert.equal(bad.ok, false);
  assert.ok(bad.error);
});
