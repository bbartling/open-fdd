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

// ---- read-only policy ---------------------------------------------------------------------
const P0 = () => lib.sparqlPrefixes(TTL);

test("policy: SELECT, ASK, CONSTRUCT, DESCRIBE are allowed (also after PREFIX/BASE, comments, any case)", () => {
  for (const q of [
    "SELECT * WHERE { ?s ?p ?o } LIMIT 1",
    "select * where { ?s ?p ?o }",
    "# insert delete load\nASK { ?s ?p ?o }",
    "PREFIX a: <http://x/> BASE <http://y/>\nCONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "DESCRIBE <http://x/a>",
    // the words inside literals, IRIs, comments and variable/prefixed names are data, not operations
    'SELECT ?load ?service WHERE { ?s <http://x/insert> "DELETE SERVICE LOAD" ; ex:drop ?load } # CLEAR',
    "SELECT * WHERE { ?s ?p ?o . FILTER(?o < 5 && ?o > 1) }",
  ]) assert.equal(typeof lib.sparqlCheckQuery(q).form, "string", q);
});

test("policy: updates are refused", () => {
  for (const q of [
    "INSERT DATA { <http://x/a> <http://x/b> <http://x/c> }",
    "insert data { <http://x/a> <http://x/b> 1 }",
    "DELETE WHERE { ?s ?p ?o }",
    "DELETE DATA { <http://x/a> <http://x/b> 1 }",
    "WITH <http://g> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "LOAD <http://evil.example/data.ttl>",
    "CLEAR ALL", "DROP ALL", "CREATE GRAPH <http://g>", "COPY DEFAULT TO <http://g>", "MOVE DEFAULT TO <http://g>", "ADD DEFAULT TO <http://g>",
    "PREFIX a: <http://x/>\nINSERT { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "# SELECT\nCLEAR DEFAULT",
    "SELECT * WHERE { ?s ?p ?o } ; DROP ALL",
    "ASK { ?s ?p ?o } ; INSERT DATA { <http://x/a> <http://x/b> 1 }",
    "S\\u0045LECT * { ?s ?p ?o } ; \\u0049NSERT DATA { <http://x/a> <http://x/b> 1 }",
  ]) assert.throws(() => lib.sparqlCheckQuery(q), /read-only|not allowed|only SELECT/, q);
});

test("policy: SERVICE is refused, however it is hidden", () => {
  for (const q of [
    "SELECT * WHERE { SERVICE <http://evil.example/sparql> { ?s ?p ?o } }",
    "SELECT * WHERE { service silent <http://evil.example/sparql> { ?s ?p ?o } }",
    "SELECT * WHERE { ?s ?p ?o .SERVICE <http://evil.example/s> { ?a ?b ?c } }",
    "SELECT * WHERE { { SELECT * WHERE { SERVICE ?e { ?s ?p ?o } } } }",
    "SELECT * WHERE { ?s ?p ?o }\nSERVICE <http://x/>{}",
    "SELECT * WHERE { \\u0053ERVICE <http://evil.example/s> { ?a ?b ?c } }",
  ]) assert.throws(() => lib.sparqlCheckQuery(q), /SERVICE/, q);
});

test("policy: other garbage, empty and oversize queries", () => {
  assert.throws(() => lib.sparqlCheckQuery("SELEC nope"), /only SELECT/);
  assert.throws(() => lib.sparqlCheckQuery("{ ?s ?p ?o }"), /only SELECT/);
  assert.throws(() => lib.sparqlCheckQuery("   "), /required/);
  assert.throws(() => lib.sparqlCheckQuery(5), /required/);
  assert.throws(() => lib.sparqlCheckQuery("SELECT * WHERE { ?s ?p ?o } #" + "x".repeat(lib.SPARQL_QUERY_CAP)), /longer than 20000/);
  assert.equal(lib.SPARQL_QUERY_CAP, 20000);
});

test("policy is enforced on the engine path: sparqlExec and runSparql reject before touching the store", () => {
  let touched = 0;
  const spy = { query() { touched++; throw new Error("must not run"); } };
  assert.throws(() => lib.sparqlExec(spy, "DROP ALL"), /read-only|only SELECT/);
  assert.throws(() => lib.sparqlExec(spy, "SELECT * { SERVICE <http://x/> { ?s ?p ?o } }"), /SERVICE/);
  assert.equal(touched, 0);
  assert.throws(() => hook.runSparql(TTL, `${P0()}\nINSERT DATA { <urn:a> <urn:b> <urn:c> }`, "json", { ox }), /read-only|only SELECT/);
  assert.throws(() => hook.runSparql(TTL, "SELECT * { SERVICE <http://127.0.0.1:1/> { ?s ?p ?o } }", "json", { ox }), /SERVICE/);
});

// ---- single execution (mock store) ---------------------------------------------------------
const term = (type, value) => ({ type, value });
function mockStore(select) {
  const seen = [];
  return { seen, query(q, o) { seen.push({ q, o }); return select(q, o); } };
}

test("SELECT evaluates exactly once (vars come from the same JSON result), also with zero rows", () => {
  const json = JSON.stringify({ head: { vars: ["a", "b"] }, results: { bindings: [{ a: term("uri", "urn:x"), b: term("literal", "7") }, { a: term("bnode", "b1") }] } });
  const st = mockStore(() => json);
  const r = lib.sparqlExec(st, "SELECT ?a ?b WHERE { ?a ?p ?b }");
  assert.equal(st.seen.length, 1);
  assert.deepEqual(r, { kind: "select", vars: ["a", "b"], rows: [["urn:x", "7"], ["_:b1", null]], total: 2, truncated: false });
  const empty = mockStore(() => JSON.stringify({ head: { vars: ["a", "b"] }, results: { bindings: [] } }));
  assert.deepEqual(lib.sparqlExec(empty, "SELECT ?a ?b WHERE { ?a ?p ?b }").vars, ["a", "b"]);
  assert.equal(empty.seen.length, 1);
  const capped = lib.sparqlExec(mockStore(() => json), "SELECT ?a ?b WHERE { ?a ?p ?b }", 1);
  assert.equal(capped.rows.length, 1);
  assert.equal(capped.truncated, true);
  assert.equal(capped.total, 2);
});

test("ASK and CONSTRUCT also evaluate once", () => {
  const ask = mockStore(() => true);
  assert.deepEqual(lib.sparqlExec(ask, "ASK { ?s ?p ?o }"), { kind: "ask", value: true });
  assert.equal(ask.seen.length, 1);
  const g = mockStore(() => "<urn:a> <urn:b> <urn:c> .");
  assert.equal(lib.sparqlExec(g, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }").kind, "graph");
  assert.equal(g.seen.length, 1);
});

test("real engine: SELECT on the fixture returns the column and string rows", () => {
  const store = lib.sparqlLoadStore(ox, TTL);
  const r = lib.sparqlExec(store, `${P0()}\nSELECT ?l WHERE { ?p a phIoT:point ; rdfs:label ?l } ORDER BY ?l`);
  assert.deepEqual(r.vars, ["l"]);
  assert.ok(r.rows.length >= 6 && r.rows.every((x) => typeof x[0] === "string"));
});

// ---- model size limit (hook) ---------------------------------------------------------------
test("a model over the triple limit is refused before evaluation; args can only lower the limit", () => {
  let evaluated = 0;
  const fakeOx = { Store: class { load() {} get size() { return 600000; } query() { evaluated++; return true; } } };
  assert.throws(() => hook.runSparql("", "ASK { ?s ?p ?o }", "json", { ox: fakeOx }), /600000 triples.*limit of 500000/);
  assert.equal(evaluated, 0);
  const small = { Store: class { load() {} get size() { return 10; } query() { evaluated++; return true; } } };
  assert.throws(() => hook.runSparql("", "ASK { ?s ?p ?o }", "json", { ox: small, maxTriples: 5 }), /limit of 5/);
  assert.equal(hook.runSparql("", "ASK { ?s ?p ?o }", "json", { ox: small }).value, true);
  assert.equal(hook.maxTriples(10), 10);
  assert.equal(hook.maxTriples(10 ** 9), 500000);        // a caller cannot raise it
  process.env.OPENFDD_SPARQL_MAX_TRIPLES = "1000";
  try { assert.equal(hook.maxTriples(), 1000); assert.equal(hook.maxTriples(5000), 1000); }
  finally { delete process.env.OPENFDD_SPARQL_MAX_TRIPLES; }
});

test("hook handle() reports a policy violation as ok:false", async () => {
  const http = { post: async () => ({ data: { points: [] } }), defaults: { baseURL: "http://127.0.0.1:8080" } };
  const out = await hook.handle({ sdk: { http, logEvent() {} }, args: { query: "DROP ALL" } });
  assert.equal(out.ok, false);
  assert.match(out.error, /read-only|only SELECT/);
});

// ---- worker client (fake Worker): timeout terminates it -------------------------------------
function fakeWorkerFactory(behaviour) {
  const made = [];
  const spawn = () => {
    const w = { terminated: false, posted: [], onmessage: null, onerror: null,
      postMessage(m) { this.posted.push(m); behaviour(w, m); },
      terminate() { this.terminated = true; } };
    made.push(w);
    return w;
  };
  return { spawn, made };
}

test("worker client: result flows back; the Turtle is sent once until it changes", async () => {
  const { spawn, made } = fakeWorkerFactory((w, m) => setTimeout(() => w.onmessage({ data: { id: m.id, ok: true, result: { kind: "ask", value: true } } }), 1));
  const c = lib.sparqlWorkerClient(spawn, 500);
  assert.deepEqual(await c.run("ttl-1", "ASK {}", 10), { kind: "ask", value: true });
  await c.run("ttl-1", "ASK {}", 10);
  await c.run("ttl-2", "ASK {}", 10);
  assert.equal(made.length, 1);
  assert.deepEqual(made[0].posted.map((m) => m.turtle), ["ttl-1", undefined, "ttl-2"]);
  c.dispose();
  assert.equal(made[0].terminated, true);
});

test("worker client: a query that never answers is stopped by terminating the worker; the next run uses a new one", async () => {
  let hang = true;
  const { spawn, made } = fakeWorkerFactory((w, m) => { if (!hang) setTimeout(() => w.onmessage({ data: { id: m.id, ok: true, result: { kind: "ask", value: false } } }), 1); });
  const c = lib.sparqlWorkerClient(spawn, 30);
  await assert.rejects(c.run("t", "SELECT * { ?s ?p ?o }", 10), (e) => e.timedOut === true && /stopped after/.test(e.message));
  assert.equal(made[0].terminated, true);
  hang = false;
  assert.equal((await c.run("t", "ASK {}", 10)).value, false);
  assert.equal(made.length, 2);
  assert.equal(made[1].posted[0].turtle, "t");            // fresh worker gets the Turtle again
  c.dispose();
});

test("worker client: worker errors reject; a worker that cannot start is flagged for fallback", async () => {
  const bad = fakeWorkerFactory((w, m) => setTimeout(() => w.onmessage({ data: { id: m.id, ok: false, error: "parse error" } }), 1));
  const c1 = lib.sparqlWorkerClient(bad.spawn, 500);
  await assert.rejects(c1.run("t", "SELECT", 1), /parse error/);
  await assert.rejects(c1.run("t", "SELECT", 1), /parse error/);
  assert.equal(bad.made[0].posted[1].turtle, "t");        // after a failure the Turtle is re-sent
  const dead = fakeWorkerFactory((w) => setTimeout(() => w.onerror({ message: "blocked" }), 1));
  const c2 = lib.sparqlWorkerClient(dead.spawn, 500);
  await assert.rejects(c2.run("t", "ASK {}", 1), (e) => e.workerUnavailable === true);
  assert.equal(dead.made[0].terminated, true);
  const nowasm = fakeWorkerFactory((w, m) => setTimeout(() => w.onmessage({ data: { id: m.id, ok: false, unavailable: true, error: "no wasm" } }), 1));
  await assert.rejects(lib.sparqlWorkerClient(nowasm.spawn, 500).run("t", "ASK {}", 1), (e) => e.workerUnavailable === true);
  const throwing = lib.sparqlWorkerClient(() => { throw new Error("Worker blocked by CSP"); }, 500);
  await assert.rejects(throwing.run("t", "ASK {}", 1), (e) => e.workerUnavailable === true);
});

test("worker side: loaded as a classic worker script it answers messages (engine load failure -> unavailable)", async () => {
  const posted = [];
  const ctx = vm.createContext({ console, URL, location: { href: "http://h/api/v1/apps/static/open-fdd/sparql.js?v=abc" }, postMessage: (m) => posted.push(m) });
  vm.runInContext("globalThis.WorkerGlobalScope = class {}; Object.setPrototypeOf(globalThis, WorkerGlobalScope.prototype);", ctx);
  vm.runInContext(readFileSync(new URL("sparql.js", dir), "utf8"), ctx, { filename: "sparql.js" });
  assert.equal(typeof vm.runInContext("onmessage", ctx), "function");
  await vm.runInContext("onmessage", ctx)({ data: { id: 7, query: "ASK {}", turtle: "", cap: 5 } });
  assert.equal(posted.length, 1);
  assert.equal(posted[0].id, 7);
  assert.equal(posted[0].ok, false);
  assert.equal(posted[0].unavailable, true);          // dynamic import() is not available here -> page falls back
});
