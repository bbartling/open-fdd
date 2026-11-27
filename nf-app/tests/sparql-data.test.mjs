// node --test nf-app/tests/sparql-data.test.mjs — the sparql-data hook (SPARQL -> points -> history) and the rdf hook.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/sparql_data.js");
const rdf = require("../hooks/rdf.js");

const fixture = JSON.parse(readFileSync(new URL("../../tools/rdf-check/fixtures/model.json", import.meta.url), "utf8"));
const SAT = "11111111-0000-4000-8000-000000000004";
const OAT = "11111111-0000-4000-8000-000000000005";
const FAN = "11111111-0000-4000-8000-000000000006";
const T0 = Date.parse("2026-01-01T00:00:00Z");

const PTS_Q = `SELECT ?uuid ?equip WHERE {
  ?p a phIoT:point ; phIoT:equipRef ?e ; ref:hasExternalReference/ref:hasTimeseriesId ?uuid .
  ?e rdfs:label ?equip . }`;

/** Mock NF: point/query from the fixture; point/data from `series` {uuid: [[ms, value]]} (raw or AVERAGE buckets). */
function mockSdk({ records = fixture.records, series = {}, calls = [], cap = 10000 } = {}) {
  const model = records.filter((r) => r.pointType !== "POINT");
  const pts = records.filter((r) => r.pointType === "POINT");
  const http = {
    defaults: { baseURL: "http://127.0.0.1:8080" },
    post: async (url, body) => {
      assert.equal(url, "/api/v1/point/query");
      return { data: { points: body.layer === "model" ? model : pts, totalCount: body.layer === "model" ? model.length : pts.length } };
    },
    get: async (url) => {
      calls.push(url);
      const u = new URL("http://x" + url);
      assert.equal(u.pathname, "/api/v1/point/data");
      const from = Date.parse(u.searchParams.get("from")), to = Date.parse(u.searchParams.get("to"));
      const data = u.searchParams.getAll("uuids").map((id) => ({
        uuid: id,
        values: (series[id] || []).filter(([t]) => t >= from && t < to).slice(0, cap)
          .map(([t, v]) => (typeof v === "string" ? { ts: new Date(t).toISOString(), string: v } : { ts: new Date(t).toISOString(), double: v })),
      }));
      return { data: { data } };
    },
  };
  const logs = [];
  return { sdk: { http, logEvent: (m) => logs.push(m) }, logs, calls };
}

const range = (hours) => ({ from: new Date(T0).toISOString(), to: new Date(T0 + hours * 3600e3).toISOString() });
const ramp = (n, f = (i) => i) => Array.from({ length: n }, (_, i) => [T0 + i * 300e3, f(i)]);

test("args: SELECT and ASK only; CONSTRUCT, DESCRIBE, updates and SERVICE are refused", () => {
  for (const q of ["CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "DESCRIBE <urn:x>", "DELETE WHERE { ?s ?p ?o }",
    "SELECT * WHERE { SERVICE <http://e.test/> { ?s ?p ?o } }", "", "SELEC"]) {
    assert.throws(() => hook.validateArgs({ query: q, ...range(1) }), /SELECT|ASK|read-only|SERVICE|required|allowed/i, q);
  }
  assert.equal(hook.validateArgs({ query: "ASK { ?s ?p ?o }", ...range(1) }).form, "ASK");
});

test("args: caps can only be lowered; time range is checked", () => {
  const a = hook.validateArgs({ query: PTS_Q, ...range(1), pointLimit: "999", maxBytes: "999999999", maxRows: "999999" });
  assert.equal(a.pointLimit, 200);
  assert.ok(a.maxBytes <= hook.LIMITS.maxBytes);
  assert.ok(a.maxRows <= hook.LIMITS.maxRows);
  assert.equal(hook.validateArgs({ query: PTS_Q, ...range(1), pointLimit: "5" }).pointLimit, 5);
  assert.throws(() => hook.validateArgs({ query: PTS_Q, from: range(1).to, to: range(1).from }), /before/);
  assert.throws(() => hook.validateArgs({ query: PTS_Q, from: "nope", to: range(1).to }), /from/);
  assert.throws(() => hook.validateArgs({ query: PTS_Q, ...range(24 * 40), source: "nf" }), /days/);
  assert.throws(() => hook.validateArgs({ query: PTS_Q, ...range(1), bucket: "3 fortnights" }), /bucket/);
  assert.throws(() => hook.validateArgs({ query: PTS_Q, ...range(1), bucket: "raw", source: "timescale" }), /raw/);
  const w = hook.validateArgs({ query: PTS_Q, windowHours: "2" });   // widened to whole 5-minute buckets
  const span = Date.parse(w.to) - Date.parse(w.from);
  assert.ok(span >= 2 * 3600e3 && span <= 2 * 3600e3 + 300e3, String(span));
  assert.equal(Date.parse(w.from) % 300e3, 0); assert.equal(Date.parse(w.to) % 300e3, 0);
  // a bucketed window must sit on bucket boundaries (epoch-aligned), else one bucket would be split across pages
  assert.throws(() => hook.validateArgs({ query: PTS_Q, from: "2026-01-05T00:02:00Z", to: "2026-01-05T01:00:00Z" }),
    (e) => e.code === "unaligned" && /multiples of the bucket/.test(e.message));
  assert.equal(hook.validateArgs({ query: PTS_Q, from: "2026-01-05T00:02:00Z", to: "2026-01-05T01:00:00Z", bucket: "raw" }).bucket, "raw");
  // StartHook string map -> numbers
  assert.equal(hook.argsOf({ args: { pointOffset: "3" } }).pointOffset, 3);
});

test("prefixes the model uses are added when the query leaves them out", () => {
  const q = hook.withPrefixes("SELECT ?p WHERE { ?p a phIoT:point }", "@prefix phIoT: <https://project-haystack.org/def/phIoT/> .\n@prefix local: <urn:t:> .");
  assert.match(q, /^PREFIX phIoT: <https:\/\/project-haystack.org\/def\/phIoT\/>/m);
  const own = hook.withPrefixes("PREFIX phIoT: <urn:mine/>\nSELECT * WHERE {}", "@prefix phIoT: <https://project-haystack.org/def/phIoT/> .");
  assert.equal(own, "PREFIX phIoT: <urn:mine/>\nSELECT * WHERE {}");
});

test("handle: SELECT -> model points with unit/kind/tags, history raw, answer logged once", async () => {
  const { sdk, logs, calls } = mockSdk({ series: { [SAT]: ramp(12, (i) => 55 + i), [OAT]: ramp(12, () => 40) } });
  const out = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), bucket: "raw" } });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.kind, "select");
  assert.equal(out.uuid_var, "uuid");
  assert.equal(out.points_total, 4);                               // SAT, OAT, FAN-C, SPARE (equip points)
  assert.deepEqual(Object.keys(out.points).sort(), [SAT, OAT, FAN, "11111111-0000-4000-8000-000000000007"].sort());
  assert.equal(out.points[SAT].unit, "degF");
  assert.equal(out.points[SAT].equip, "AHU-1");
  assert.equal(out.points[SAT].site, "site-a");
  assert.ok(out.points[SAT].tags.includes("discharge"));
  assert.equal(out.points[FAN].kind, "Bool");
  assert.deepEqual(out.equips, [{ site: "site-a", id: "AHU-1", dis: "AHU-1", tags: ["equip", "ahu", "rooftop"] }]);
  assert.equal(out.series[SAT].length, 12);
  assert.deepEqual(out.series[SAT][0], [T0, 55]);
  assert.equal(out.complete, true);
  assert.equal(out.next_from, null);
  assert.equal(out.source, "nf");
  assert.equal(out.bucket, "raw");
  assert.ok(out.rows.length >= 4);
  assert.equal(logs.length, 1);
  assert.deepEqual(JSON.parse(logs[0]), out);
  assert.ok(calls.every((c) => !/window=/.test(c)), "raw: no resample");
});

test("handle: resampled NF history asks for window + AVERAGE; ASK answers without data", async () => {
  const { sdk, calls } = mockSdk({ series: { [SAT]: ramp(3) } });
  const out = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), bucket: "15 minutes" } });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.window_sec, 900);
  assert.ok(calls.every((c) => /window=900s&method=AVERAGE/.test(c)));
  const ask = await hook.handle({ sdk, args: { query: "ASK { ?p a phIoT:point }", ...range(1) } });
  assert.deepEqual([ask.ok, ask.kind, ask.value], [true, "ask", true]);
});

test("handle: uuids are only taken from model points (a forged literal is not fetched)", async () => {
  const { sdk, calls } = mockSdk();
  const out = await hook.handle({ sdk, args: { query: 'SELECT ?uuid WHERE { VALUES ?uuid { "not-a-point" } }', ...range(1) } });
  assert.equal(out.ok, false);
  assert.match(out.error, /no point of the model/);
  assert.equal(calls.length, 0);
  // point IRIs work too (local:<uuid>)
  const iri = await hook.handle({ sdk, args: { query: "SELECT ?p WHERE { ?p a phIoT:point ; ph:hasTag phIoT:discharge ; ph:hasTag phScience:temp }", ...range(1) } });
  assert.equal(iri.ok, true, JSON.stringify(iri));
  assert.deepEqual(Object.keys(iri.points), [SAT]);
  assert.equal(iri.uuid_var, "p");
});

test("handle: more points than pointLimit pages with pointOffset, nothing dropped", async () => {
  const { sdk } = mockSdk();
  const a = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), pointLimit: "3" } });
  assert.equal(a.ok, true, JSON.stringify(a));
  assert.equal(Object.keys(a.points).length, 3);
  assert.equal(a.next_point_offset, 3);
  const b = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), pointLimit: "3", pointOffset: "3", includeRows: "false" } });
  assert.equal(Object.keys(b.points).length, 1);
  assert.equal(b.next_point_offset, null);
  assert.equal(b.rows, undefined);
  assert.equal(new Set([...Object.keys(a.points), ...Object.keys(b.points)]).size, 4);
});

test("handle: the byte cap cuts on a timestamp and says where to continue", async () => {
  const { sdk } = mockSdk({ series: { [SAT]: ramp(200, (i) => 50 + i / 7), [OAT]: ramp(200, (i) => 30 + i / 3) } });
  const args = { query: PTS_Q, ...range(200 * 300 / 3600), bucket: "raw", maxBytes: "6000" };
  const first = await hook.handle({ sdk, args });
  assert.equal(first.ok, true, JSON.stringify(first).slice(0, 300));
  assert.equal(first.complete, false);
  const cut = Date.parse(first.next_from);
  for (const s of Object.values(first.series)) for (const [t] of s) assert.ok(t < cut);
  assert.equal(first.series[SAT].length, first.series[OAT].length, "every point is complete up to the cut");
  // page on: the union of pages is the whole series
  let from = first.next_from, got = first.series[SAT].length, pages = 1;
  while (from) {
    const p = await hook.handle({ sdk, args: { ...args, from, includeRows: "false" } });
    assert.equal(p.ok, true);
    got += p.series[SAT].length; from = p.next_from; pages++;
    assert.ok(pages < 100);
  }
  assert.equal(got, 200);
});

test("handle: NF's 10k raw sample cap splits the window instead of losing samples", async () => {
  const n = 30;
  const { sdk, calls } = mockSdk({ series: { [SAT]: ramp(n) }, cap: 8 });
  const out = await hook.handle({ sdk, args: { query: 'SELECT ?uuid WHERE { BIND("' + SAT + '" AS ?uuid) }', ...range(n * 300 / 3600), bucket: "raw", nfSampleCap: "8" } });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.series[SAT].length, n);
  assert.ok(calls.length > 1);
});

test("handle: text values survive (String points), booleans become 0/1", async () => {
  const recs = fixture.records.map((r) => (r.uuid === FAN ? { ...r } : r));
  const { sdk } = mockSdk({ records: recs, series: { [SAT]: [[T0, "Occupied"]] } });
  const out = await hook.handle({ sdk, args: { query: 'SELECT ?uuid WHERE { BIND("' + SAT + '" AS ?uuid) }', ...range(1) } });
  assert.deepEqual(out.series[SAT], [[T0, "Occupied"]]);
  assert.equal(hook.sampleValue({ boolean: true }), 1);
  assert.equal(hook.sampleValue({ unsigned: "3" }), 3);
});

test("handle: source timescale without a connection is a clear error; auto falls back to NF", async () => {
  const { sdk } = mockSdk({ series: { [SAT]: ramp(2) } });
  const ts = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), source: "timescale", bucket: "5 minutes" } });
  assert.equal(ts.ok, false);
  assert.match(ts.error, /timescale/i);
  const auto = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), bucket: "5 minutes" } });
  assert.equal(auto.source, "nf");
});

test("handle: timescale source maps history buckets (avg) and refuses a truncated answer", async () => {
  const { sdk } = mockSdk();
  const fake = {
    connect: async () => ({ end: async () => {} }),
    historyRoute: async (c, a) => ({ bucket: "5 minutes", truncated: false,
      rows: [{ point_uuid: a.uuids[0], bucket: new Date(T0).toISOString(), avg: 1.5, min: 1, max: 2, n: 3 }] }),
  };
  const out = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), source: "timescale", bucket: "5 minutes" },
    config: { timescale: '{"host":"h","database":"d","user":"u","password":"p"}' }, deps: { ts: fake } });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.source, "timescale");
  const first = Object.keys(out.series).find((k) => out.series[k].length);
  assert.deepEqual(out.series[first], [[T0, 1.5]]);
  fake.historyRoute = async () => ({ truncated: true, rows: [] });
  const bad = await hook.handle({ sdk, args: { query: PTS_Q, ...range(1), source: "timescale", bucket: "5 minutes" },
    config: { timescale: '{"host":"h","database":"d","user":"u","password":"p"}' }, deps: { ts: fake } });
  assert.equal(bad.ok, false);
  assert.equal(bad.error_code, "too_large");
});

test("rdf hook: Turtle pages join to the full model Turtle", async () => {
  const { sdk } = mockSdk();
  const whole = (await rdf.buildTurtle(sdk, {})).turtle;
  let text = "", offset = 0, pages = 0;
  for (;;) {
    const r = await rdf.handle({ sdk, args: { offset: String(offset), limit: "500" } });
    assert.equal(r.ok, true, JSON.stringify(r));
    assert.equal(r.total_chars, whole.length);
    text += r.turtle; pages++;
    if (r.next_offset == null) break;
    offset = r.next_offset;
  }
  assert.equal(text, whole);
  assert.ok(pages > 1);
  assert.match(whole, /ref:hasTimeseriesId "11111111-0000-4000-8000-000000000004"/);
  const bad = await rdf.handle({ sdk, args: { offset: "-1" } });
  assert.equal(bad.ok, false);
});

test("model.js exports an explicit ofddRole attr as local:ofddRole", async () => {
  const recs = fixture.records.map((r) => (r.uuid === SAT ? { ...r, attrs: { ...r.attrs, ofddRole: "discharge_air_temperature" } } : r));
  const { sdk } = mockSdk({ records: recs });
  const ttl = (await rdf.buildTurtle(sdk, {})).turtle;
  assert.match(ttl, /local:ofddRole "discharge_air_temperature"/);
  const out = await hook.handle({ sdk, args: { query: "SELECT ?p ?role WHERE { ?p local:ofddRole ?role }", ...range(1) } });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.points[SAT].role, "discharge_air_temperature");
});

test("hardening: runaway SPARQL is stopped by the worker timeout; huge results are refused, not truncated", async () => {
  const ttl = "@prefix ex: <urn:ex:> .\n" + Array.from({ length: 200 }, (_, i) => `ex:s${i} ex:p ex:o${i} .`).join("\n");
  await assert.rejects(hook.evaluate(ttl, "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }", { timeoutMs: 50 }), /wall-clock/);
  const r = await hook.evaluate(ttl, "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f }", { cap: 10 });
  assert.equal(r.rows.length, 10);
  assert.equal(r.truncated, true, "engine-side LIMIT cap+1 still tells truncation");
  const bounded = await hook.evaluate(ttl, "PREFIX ex: <urn:ex:>\nSELECT ?s WHERE { ?s ex:p ?o } ORDER BY ?s", { cap: 5000 });
  assert.equal(bounded.rows.length, 200);
});

test("hardening: NF sample cap at the minimum split is an error, never a silent partial series", async () => {
  const many = Array.from({ length: 20 }, () => [T0, 1]);       // 20 samples at one timestamp, cap 8
  const { sdk } = mockSdk({ series: { [SAT]: many }, cap: 8 });
  const out = await hook.handle({ sdk, args: { query: 'SELECT ?uuid WHERE { BIND("' + SAT + '" AS ?uuid) }', ...range(1), bucket: "raw", nfSampleCap: "8" } });
  assert.equal(out.ok, false);
  assert.equal(out.error_code, "too_large");
});

test("hardening: the byte cap counts UTF-8 bytes; every answer fits", async () => {
  const text = Array.from({ length: 200 }, (_, i) => [T0 + i * 300e3, "°C ±°F — occupied ✓"]);
  const { sdk, logs } = mockSdk({ series: { [SAT]: text } });
  const args = { query: 'SELECT ?uuid WHERE { BIND("' + SAT + '" AS ?uuid) }', ...range(17), bucket: "raw", maxBytes: "4000" };
  const out = await hook.handle({ sdk, args });
  assert.equal(out.ok, true, JSON.stringify(out).slice(0, 300));
  assert.equal(out.complete, false);
  assert.ok(Buffer.byteLength(logs[0], "utf8") <= 4000, `logged ${Buffer.byteLength(logs[0], "utf8")} bytes`);
});

test("hardening: paging is pinned to one model snapshot", async () => {
  const { sdk } = mockSdk({ series: { [SAT]: ramp(3) } });
  const q = { query: PTS_Q, ...range(1), pointLimit: "2" };
  const a = await hook.handle({ sdk, args: q });
  assert.match(a.snapshot, /^[0-9a-f]{64}$/);
  const b = await hook.handle({ sdk, args: { ...q, pointOffset: "2", snapshot: a.snapshot } });
  assert.equal(b.ok, true, JSON.stringify(b));
  const changed = mockSdk({ records: fixture.records.filter((r) => r.uuid !== OAT) });
  const c = await hook.handle({ sdk: changed.sdk, args: { ...q, pointOffset: "2", snapshot: a.snapshot } });
  assert.equal(c.ok, false);
  assert.match(c.error, /changed/);
  const t1 = await rdf.handle({ sdk, args: { limit: "300" } });
  const t2 = await rdf.handle({ sdk: changed.sdk, args: { offset: String(t1.next_offset), limit: "300", snapshot: t1.snapshot } });
  assert.equal(t2.ok, false);
  assert.match(t2.error, /changed/);
});

test("rdf hook: byte limit never splits a UTF-8 character", () => {
  const s = "ab°😀c";
  assert.equal(rdf.sliceBytes(s, 0, 4), "ab°");
  assert.equal(rdf.sliceBytes(s, 3, 4), "😀");
  assert.throws(() => rdf.sliceBytes(s, 3, 3), /smaller/);
});

test("the shipped example query (examples/sparql_data/ahu_points.rq) finds the AHU and weather points", async () => {
  const q = readFileSync(new URL("../../examples/sparql_data/ahu_points.rq", import.meta.url), "utf8");
  const { sdk } = mockSdk({ series: { [SAT]: ramp(3), [OAT]: ramp(3) } });
  const out = await hook.handle({ sdk, args: { query: q, ...range(1), bucket: "raw" } });
  assert.equal(out.ok, true, out.error);
  assert.equal(out.uuid_var, "uuid");
  assert.ok(out.points[SAT], "AHU supply air temp");
  assert.ok(Object.values(out.points).some((p) => p.tags.includes("weather")), "weather point");
  assert.ok(Object.values(out.points).every((p) => p.equip === "AHU-1" || p.tags.includes("weather")));
});
test("hardening: the RSS watchdog stops a query whose WebAssembly memory grows past the limit", async () => {
  const turtle = "@prefix ex: <urn:ex:> .\nex:a ex:p ex:b .\n";
  let n = 0;
  const rss = () => (n++ === 0 ? 0 : 1e12);   // first read is the baseline, then a huge jump
  await assert.rejects(hook.evaluate(turtle, "SELECT * WHERE { ?s ?p ?o }", { rss, everyMs: 1, maxGrowthMb: 1 }), (e) => {
    assert.match(String(e.message), /memory limit/);
    assert.equal(e.code, "too_large");
    return true;
  });
  const ok = await hook.evaluate(turtle, "SELECT * WHERE { ?s ?p ?o }", { rss: () => 0 });
  assert.equal(ok.rows.length, 1);
});

test("rdf hook: the logged JSON line fits the limit even for quote-heavy Turtle; model_changed keeps its code", async () => {
  const recs = fixture.records.map((r) => (r.pointType === "POINT" ? { ...r, attrs: { ...r.attrs, dis: '"q"\n"q"\n"q"\n"q"' } } : r));
  const { sdk } = mockSdk({ records: recs });
  const a = await rdf.handle({ sdk, args: { limit: "2000" } });
  assert.equal(a.ok, true, a.error);
  assert.ok(Buffer.byteLength(JSON.stringify(a), "utf8") <= 2000);
  const b = await rdf.handle({ sdk, args: { offset: "0", snapshot: "not-the-snapshot" } });
  assert.equal(b.ok, false);
  assert.equal(b.error_code, "model_changed");
});
test("a windowHours-only request gets the bucket-aligned default window", () => {
  const args = hook.argsOf({ args: { query: "ASK { ?s ?p ?o }", windowHours: "6" } });
  assert.equal(args.from, undefined, "windowHours is not expanded to unaligned bounds before validation");
  const v = hook.validateArgs(args, { now: Date.parse("2026-11-14T12:03:17Z") });
  assert.equal(v.form, "ASK");
});

// #1635: the answer carries the run proof the FDD hook resolves per equipment, so client rules gate like the hook / SQL.
const SAT_ONLY_Q = `SELECT ?uuid WHERE { ?p a phIoT:point ; ref:hasExternalReference/ref:hasTimeseriesId ?uuid .
  FILTER(STR(?uuid) = "${SAT}") }`;

test("handle: operating_status is the FDD hook's resolution; a proof point off the page comes back in run_proof_series", async () => {
  const { sdk } = mockSdk({ series: { [SAT]: ramp(12), [FAN]: ramp(12, (i) => (i < 6 ? 1 : 0)) } });
  const ans = await hook.handle({ sdk, args: { query: SAT_ONLY_Q, ...range(1) } });
  assert.equal(ans.ok, true, ans.error);
  assert.deepEqual(Object.keys(ans.series), [SAT], "series holds only the page's points");
  assert.equal(ans.operating_status.length, 1);
  assert.deepEqual({ ...ans.operating_status[0], site: undefined }, { site: undefined, equip: "AHU-1", uuid: FAN, source: "command", tier: "own", via: "self", unit: "" });
  assert.deepEqual(ans.run_proof_series[FAN].map(([, v]) => v), [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]);
});

test("handle: an equipment with no status or command bound gets the no-binding marker (uuid null)", async () => {
  const records = fixture.records.filter((r) => r.uuid !== FAN);
  const { sdk } = mockSdk({ records, series: { [SAT]: ramp(12) } });
  const ans = await hook.handle({ sdk, args: { query: SAT_ONLY_Q, ...range(1) } });
  assert.equal(ans.ok, true, ans.error);
  assert.equal(ans.operating_status[0].uuid, null);
  assert.deepEqual(ans.run_proof_series, {});
});

test("runProofOf: an explicit ofddRole operating_status pin wins; pinned own status is the last resort", () => {
  const e = { site: "s", id: "U1" };
  const pt = (uuid, role) => ({ uuid, equipRef: "U1", siteRef: "s", units: "", tags: [], rec: { attrs: { ofddRole: role } } });
  const model = { equips: [], points: [pt("st", "supply_fan_operating_status"), pt("rp", "operating_status")] };
  assert.equal(hook.runProofOf(model, [e])[0].uuid, "rp");
  assert.equal(hook.runProofOf({ equips: [], points: [pt("st", "supply_fan_operating_status")] }, [e])[0].uuid, "st");
  assert.equal(hook.runProofOf({ equips: [], points: [] }, [e])[0].uuid, null);
});
