// 5.0.6 (#1550): one robust pager per runtime (hooks/lib/paging.js, static/nf.js pageAll, lite hook pageAll) and the
// hook settings NF actually stores (app options -> ctx.config scalars: lib/settings.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { EventEmitter } from "node:events";

const require = createRequire(import.meta.url);
const paging = require("../hooks/lib/paging.js");
const settings = require("../hooks/lib/settings.js");
const tsLib = require("../hooks/lib/timescale.js");
const fdd = require("../hooks/fdd.js");
const weather = require("../hooks/weather.js");
const history = require("../hooks/history.js");
const liteWeather = require("../../lite/hooks/open_meteo_weather.js");

// ---- fake NF servers ---------------------------------------------------------------------------------------------
const rec = (uuid, extra = {}) => ({ uuid, name: uuid, layer: "model", pointType: "POINT", attrs: { markers: "point" }, ...extra });
const filler = (prefix, n) => Array.from({ length: n }, (_, i) => rec(`${prefix}-${String(i).padStart(4, "0")}`));

/** NF 3.10.x point/query: pageOffset + pageSize, totalCount, NO nextPageToken. `maxSize` = a server cap on pageSize. */
const offsetServer = (all, { maxSize = Infinity, log = [] } = {}) => async (body) => {
  log.push({ ...body });
  const off = Number(body.pageOffset) || 0;
  const size = Math.min(Number(body.pageSize) || 100, maxSize);
  return { points: all.slice(off, off + size), totalCount: String(all.length) };
};

/** A token-paging server (what the old code assumed): nextPageToken, no totalCount. */
const tokenServer = (all, size = 500) => async (body) => {
  const at = body.pageToken ? Number(body.pageToken.replace("t", "")) : 0;
  const points = all.slice(at, at + size);
  return { points, ...(at + size < all.length ? { nextPageToken: `t${at + size}` } : {}) };
};

/** The 5.0.3 / 5.0.5 loop, verbatim in behaviour: follows ONLY nextPageToken. */
async function oldQueryAll(serve, body) {
  const out = [];
  let pageToken = "";
  do {
    const data = await serve({ pageSize: 500, ...body, ...(pageToken && { pageToken }) });
    out.push(...(data.points || []));
    pageToken = data.nextPageToken || "";
  } while (pageToken);
  return out;
}

const httpOf = (serve) => ({ post: async (p, body) => ({ data: await serve(body) }) });

// the model layer of #1550: 994 records sorted by uuid, the SITE at position 902
const SITE = rec("m-site", { pointType: "SITE", name: "site-a", attrs: { id: "site-a", markers: "site" } });
const EQUIP = rec("m-equip", { pointType: "EQUIPMENT", name: "AHU-1", attrs: { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" } });
const MODEL_994 = [...filler("a", 900), SITE, EQUIP, ...filler("z", 92)];

// ---- 1. the pager (hooks) ----------------------------------------------------------------------------------------
test("pager: #1550 reproduced — the old token-only loop finds 0 sites in a 994-record model, the pager finds them", async () => {
  assert.equal(MODEL_994.length, 994);
  assert.equal(MODEL_994.indexOf(SITE), 900);
  const serve = offsetServer(MODEL_994);
  const old = await oldQueryAll(serve, { layer: "model" });
  assert.equal(old.length, 500, "old code reads only page 1");
  assert.equal(old.filter((r) => r.pointType === "SITE").length, 0);
  assert.equal(old.filter((r) => r.pointType === "EQUIPMENT").length, 0, "0 equipment, as in the field");
  const all = await paging.queryPoints(httpOf(serve), { layer: "model" });
  assert.equal(all.length, 994);
  assert.equal(all.filter((r) => r.pointType === "SITE").length, 1);
  assert.equal(all.filter((r) => r.pointType === "EQUIPMENT").length, 1);
  assert.equal(all.totalCount, 994, "totalCount rides along for messages");
});

test("pager: pageOffset advances by the records received, pageSize is sent, the body is kept", async () => {
  const log = [];
  const all = await paging.queryPoints(httpOf(offsetServer(MODEL_994, { log })), { layer: "model", structuredQuery: { x: 1 } });
  assert.equal(all.length, 994);
  assert.deepEqual(log.map((b) => b.pageOffset ?? 0), [0, 500]);
  assert.ok(log.every((b) => b.pageSize === 500 && b.layer === "model" && b.structuredQuery.x === 1));
  assert.ok(log.every((b) => !("pageToken" in b)));
});

test("pager: a server that caps pageSize below the request is still read to totalCount", async () => {
  const log = [];
  const all = await paging.queryPoints(httpOf(offsetServer(MODEL_994, { maxSize: 100, log })), { layer: "model" });
  assert.equal(all.length, 994);
  assert.equal(log.length, 10);
});

test("pager: an exact multiple of the page size and an empty result both end cleanly", async () => {
  assert.equal((await paging.queryPoints(httpOf(offsetServer(filler("k", 1000))), {})).length, 1000);
  assert.equal((await paging.queryPoints(httpOf(offsetServer([])), {})).length, 0);
  assert.equal((await paging.queryPoints(httpOf(offsetServer(filler("k", 3))), {})).length, 3);
});

test("pager: a next-page token is followed (no totalCount needed); a repeated token is an error", async () => {
  const all = filler("t", 1234);
  assert.equal((await paging.queryPoints(httpOf(tokenServer(all)), {})).length, 1234);
  const loopy = async () => ({ points: [rec(`r${Math.random()}`)], nextPageToken: "same" });
  await assert.rejects(paging.queryPoints(httpOf(loopy), {}), /nextPageToken repeated/);
});

test("pager: no totalCount and no token — a short page ends it", async () => {
  const noTotal = (all) => async (b) => ({ points: all.slice(Number(b.pageOffset) || 0, (Number(b.pageOffset) || 0) + b.pageSize) });
  assert.equal((await paging.queryPoints(httpOf(noTotal(filler("n", 1200))), {})).length, 1200);
});

test("pager: the hard cap is a loud PagingError, never a silent truncation", async () => {
  const serve = offsetServer(filler("c", 2500));
  await assert.rejects(paging.queryPoints(httpOf(serve), {}, { maxRecords: 1000 }),
    (e) => e.paging === true && e.name === "PagingError" && /paging cap reached after 1000 records.*totalCount 2500.*partial result/.test(e.message));
  await assert.rejects(paging.queryPoints(httpOf(serve), {}, { maxPages: 2, pageSize: 100 }), /paging cap reached after 200 records in 2 pages/);
});

test("pager: a server that ignores pageOffset (page 1 again) or ends early is an error", async () => {
  const ignoring = async () => ({ points: filler("i", 500), totalCount: "994" });
  await assert.rejects(paging.queryPoints(httpOf(ignoring), {}), /repeated records already read/);
  const early = async (b) => ({ points: Number(b.pageOffset) ? [] : filler("e", 500), totalCount: "994" });
  await assert.rejects(paging.queryPoints(httpOf(early), {}), /read 500 of totalCount 994/);
});

test("pager: listAll pages a GET list route (sites)", async () => {
  const sites = Array.from({ length: 1100 }, (_, i) => ({ id: `s${i}`, latitude: 1, longitude: 2 }));
  const urls = [];
  const http = { get: async (u) => {
    urls.push(u);
    const q = new URL(u, "http://x").searchParams;
    const off = Number(q.get("pageOffset")) || 0;
    return { data: { sites: sites.slice(off, off + Number(q.get("pageSize"))), totalCount: String(sites.length) } };
  } };
  assert.equal((await paging.listAll(http, "/api/v1/sites", "sites")).length, 1100);
  assert.equal(urls[0], "/api/v1/sites?pageSize=500");
  assert.equal(urls[1], "/api/v1/sites?pageSize=500&pageOffset=500");
});

// ---- 2. the fdd hook on the #1550 model ------------------------------------------------------------------------
const STEP = 300;
const NOW = Date.parse("2026-11-09T15:02:00Z");
const PACK = {
  poll_seconds: STEP,
  contract: { history: [{ name: "equipment_id", type: "text" }, { name: "timestamp_utc", type: "timestamp" }, { name: "fan_cmd", type: "double" }] },
  rules: { "FAN-RUNTIME-HOURS": { sql: "-", output_columns: ["equipment_id", "fan_runtime_hours", "total_hours"] } },
};
const fanPt = { uuid: "u-FANC", name: "FAN-C", layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", equipRef: "AHU-1", markers: "point,his,discharge,fan,run,cmd", dis: "FAN-C", class: "discharge-run-cmd", unit: "%" } };
const engineStub = async () => ({
  kind: "sqlite", async load() { return 288; }, async query() { return [{ equipment_id: "AHU-1", fan_runtime_hours: 24, total_hours: 24 }]; }, async close() {},
});
/** Fake NF over a model layer (offset-paged, like NF) + the site's default-layer points. */
function nfOver(model, points = [fanPt]) {
  const serveModel = offsetServer(model);
  const servePoints = offsetServer(points);
  const writes = { points: [] };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: await (body.layer === "model" ? serveModel : servePoints)(body) };
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/points/data") return { data: { success: true } };
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
      return { data: { data: uuids.map((uuid) => ({ uuid, values: [{ ts: new Date(NOW - 3600e3).toISOString(), double: 1 }] })) } };
    },
  };
}
const runFdd = (http, config = {}) => {
  const logs = [];
  return { logs, run: () => fdd.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config, pack: PACK, createEngine: engineStub, now: NOW }) };
};

test("fdd: the SITE and equipment at position ~900 of 994 model records are found (the #1550 fix)", async () => {
  const model = await fdd.loadModel(nfOver(MODEL_994), {
    ...(() => { const ctx = vm.createContext({ console }); for (const f of ["model.js"]) vm.runInContext(readFileSync(new URL(`../static/${f}`, import.meta.url), "utf8"), ctx); const g = (n) => vm.runInContext(n, ctx); return { toPoint: g("toPoint"), idOf: g("idOf"), ENTITY_TYPES: g("ENTITY_TYPES") }; })(),
  });
  assert.equal(model.sites.length, 1);
  assert.equal(model.equips.length, 1);
  assert.equal(model.points.length, 1);
  assert.deepEqual(model.read, { records: 994, total: 994, sitePointQueries: 1 });
  const r = runFdd(nfOver(MODEL_994));
  const s = await r.run();
  assert.equal(s.equips, 1, "the equipment is evaluated");
  assert.equal(s.failure, null);
  assert.ok(s.written > 0);
});

test("fdd: 0 equipment gets its own reason and fails loudly, never 'required roles missing'", async () => {
  const noEquip = filler("a", 700);      // a model that never had (or lost) its SITE / EQUIPMENT records
  const s = await runFdd(nfOver(noEquip)).run();
  assert.match(s.failure, /^model empty: 0 equipment resolved from the model layer \(0 sites, 0 equipment, 0 points; 700 model records read of totalCount 700\)/);
  assert.doesNotMatch(s.failure, /roles/);
  await assert.rejects(fdd({ sdk: { http: nfOver(noEquip), logEvent() {} }, config: {}, pack: PACK, createEngine: engineStub, now: NOW }),
    /model empty: 0 equipment/);
  // results published earlier prove equipment existed: the model was not read completely
  const prior = [{ ...rec("a-prior"), attrs: { markers: "point,his,fault,fdd", ruleRef: "FAN-RUNTIME-HOURS", fddStatus: "ok" } }];
  const s2 = await runFdd(nfOver([...noEquip, ...prior])).run();
  assert.match(s2.failure, /^model incomplete: 0 equipment resolved from the model layer .* although 1 published results exist/);
  const logs = runFdd(nfOver(noEquip));
  await logs.run();
  assert.ok(logs.logs.some((l) => /open-fdd FAILED: model empty/.test(l)), "the log says it too");
});

test("fdd: equipment but no points loaded is 'model incomplete', not a role problem", async () => {
  const s = await runFdd(nfOver([SITE, EQUIP], [])).run();
  assert.match(s.failure, /^model incomplete: 1 equipment but 0 points loaded/);
  assert.equal(s.skipped.every((x) => x.kind === "model-incomplete"), true);
});

test("fdd: a paging failure surfaces as the run's error (no silent partial model)", async () => {
  const ignoring = { post: async () => ({ data: { points: filler("q", 500), totalCount: "994" } }), get: async () => ({ data: {} }) };
  await assert.rejects(runFdd(ignoring).run(), /repeated records already read/);
});

// ---- 3. the static / Lite pagers (browser code, same algorithm) -------------------------------------------------
const editions = { app: new URL("../static/nf.js", import.meta.url), lite: new URL("../../lite/static/nf.js", import.meta.url) };
function loadNf(file, serve) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : {};
    calls.push(body);
    const data = await serve(body);
    return { ok: true, status: 200, json: async () => data };
  };
  const ctx = vm.createContext({ fetch, console, URLSearchParams, TextDecoder, atob, btoa, setTimeout: (fn) => { fn(); return 0; } });
  vm.runInContext(readFileSync(file, "utf8"), ctx, { filename: "nf.js" });
  return { queryAll: vm.runInContext("queryAll", ctx), pageAll: vm.runInContext("pageAll", ctx), calls };
}
for (const [ed, file] of Object.entries(editions)) {
  test(`[${ed}] static queryAll: offset paging reads all 994 records (SITE at 900)`, async () => {
    const { queryAll, calls } = loadNf(file, offsetServer(MODEL_994));
    const all = await queryAll({ layer: "model" });
    assert.equal(all.length, 994);
    assert.equal(all.filter((r) => r.pointType === "SITE").length, 1);
    assert.deepEqual(calls.map((b) => b.pageOffset ?? 0), [0, 500]);
  });
  test(`[${ed}] static queryAll: token paging, server page-size cap, empty result`, async () => {
    assert.equal((await loadNf(file, tokenServer(filler("t", 1234))).queryAll({})).length, 1234);
    assert.equal((await loadNf(file, offsetServer(MODEL_994, { maxSize: 100 })).queryAll({})).length, 994);
    assert.equal((await loadNf(file, offsetServer([])).queryAll({})).length, 0);
  });
  test(`[${ed}] static pageAll: cap, ignored pageOffset and early end are loud`, async () => {
    const { pageAll, queryAll } = loadNf(file, offsetServer(filler("c", 2500)));
    await assert.rejects(pageAll(async (p) => offsetServer(filler("c", 2500))(p), { maxRecords: 1000 }), /paging cap reached after 1000 records.*totalCount 2500/);
    await assert.rejects(loadNf(file, async () => ({ points: filler("i", 500), totalCount: "994" })).queryAll({}), /repeated records already read/);
    await assert.rejects(loadNf(file, async (b) => ({ points: b.pageOffset ? [] : filler("e", 500), totalCount: "994" })).queryAll({}), /read 500 of totalCount 994/);
    assert.equal((await queryAll({})).length, 2500);
  });
}

test("lite hook: the inline pager reads sites / layers by offset and is loud on a cap", async () => {
  const all = filler("l", 1100);
  assert.equal((await liteWeather.pageAll(async (p) => offsetServer(all)(p), { key: "points", what: "x" })).length, 1100);
  await assert.rejects(liteWeather.pageAll(async (p) => offsetServer(all)(p), { key: "points", what: "x", maxRecords: 600 }), /paging cap reached/);
  // siteFromModel finds a SITE at position 900 of a 994-record model
  const model = [...filler("a", 900), { ...SITE, attrs: { id: "s1", latitude: 43.07, longitude: -89.4 } }, ...filler("z", 93)];
  const s = await liteWeather.siteFromModel(httpOf(offsetServer(model)));
  assert.equal(s && s.id, "s1");
  const s2 = await weather.siteFromModel(httpOf(offsetServer(model)));
  assert.equal(s2 && s2.id, "s1");
});

// ---- 4. settings: app options as NF stores them -------------------------------------------------------------------
const PG = { host: "db.example", port: 5432, database: "nf", user: "u", password: "p4ssw0rd-secret" };

test("settings: the timescale app option arrives as a JSON STRING; fdd/history/requireConfig all accept it", () => {
  const raw = { engine: "timescale", windowHours: "24", timescale: JSON.stringify(PG), latitude: "", longitude: "" };
  const c = settings.normalizeConfig(raw);
  assert.deepEqual(c.timescale, PG);
  assert.equal(c.windowHours, 24);
  assert.equal(c.engine, "timescale");
  assert.ok(!("latitude" in c) && !("longitude" in c), "blank options are not set");
  assert.equal(typeof raw.timescale, "string", "input untouched");
  assert.deepEqual(tsLib.requireConfig(JSON.stringify(PG)), PG);
  assert.deepEqual(tsLib.requireConfig(PG), PG, "the object form still works");
  assert.deepEqual(settings.parseTimescale("postgres://u:pw@db:5432/nf"), { connectionString: "postgres://u:pw@db:5432/nf" });
  assert.deepEqual(settings.normalizeConfig({ timescale: { string: JSON.stringify(PG) }, windowHours: { signed: 12 } }).timescale, PG, "typed option values");
  assert.equal(settings.normalizeConfig({ dryRun: "true" }).dryRun, true);
  assert.deepEqual(settings.normalizeConfig({ equips: '["a","b"]' }).equips, ["a", "b"]);
});

test("settings: missing settings fail with ONE message that names where they are expected", () => {
  for (const bad of [undefined, null, "", "   ", {}, { port: 1 }]) {
    assert.throws(() => tsLib.requireConfig(bad), /Timescale connection settings not found.*app option "timescale".*JSON string.*postgres:\/\//, JSON.stringify(bad));
  }
});

test("settings: an unusable value is reported by option name and never echoes the value (it holds a password)", () => {
  const bad = '{"host":"db","password":"hunter2-secret"';          // truncated JSON
  assert.throws(() => settings.parseTimescale(bad), (e) => /app option "timescale" is set but is not valid JSON/.test(e.message) && !/hunter2/.test(e.message));
  assert.throws(() => tsLib.requireConfig("not json at all"), (e) => /app option "timescale"/.test(e.message));
  // normalizeConfig keeps it, so the consumer reports it instead of silently falling back to another engine
  assert.equal(settings.normalizeConfig({ timescale: bad }).timescale, bad);
});

test("settings: redact removes the password and URL credentials from log text", () => {
  assert.doesNotMatch(settings.redact(`connect failed for ${PG.password} at db`, PG), /p4ssw0rd/);
  assert.equal(settings.redact("could not connect to postgres://user:hunter2@db:5432/nf", undefined), "could not connect to postgres://user:***@db:5432/nf");
  assert.doesNotMatch(settings.redact("x postgres://a:b@h/d y", { connectionString: "postgres://a:b@h/d" }), /a:b@/);
  // connectionString with ?password= must be replaced BEFORE userinfo masking (#4)
  const cs = "postgres://u:old@db/nf?password=secret";
  assert.doesNotMatch(settings.redact(`fail ${cs}`, { connectionString: cs }), /secret|password=old/);
  assert.match(settings.redact(`fail ${cs}`, { connectionString: cs }), /postgres:\/\/\*\*\*/);
  // short passwords (1-2 chars) are also redacted (#5)
  assert.equal(settings.redact("pw=ab in err", { password: "ab" }), "pw=*** in err");
  assert.equal(settings.redact("pw=x in err", { password: "x" }), "pw=*** in err");
});

test("history: reads the string option, and a connection error never carries the password", async () => {
  // no pg server: connect() fails; the message must not contain the password, whatever pg wrote
  const cfg = { timescale: JSON.stringify({ ...PG, host: "127.0.0.1", port: 1 }) };
  let err;
  try { await history.handle({ sdk: { logEvent() {} }, args: { uuids: ["u"], from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" }, config: cfg }); } catch (e) { err = e; }
  const text = err ? String(err.message) : "";
  assert.doesNotMatch(text, /p4ssw0rd/);
  // a bare call with only an unparsable option is loud (misconfiguration), not a quiet "not configured" skip
  await assert.rejects(history.handle({ sdk: {}, args: {}, config: { timescale: "{broken" } }), /app option "timescale" is set but is not valid JSON/);
  // and with no option at all it is still the clean skip
  assert.deepEqual(await history.handle({ sdk: { logEvent() {} }, args: {}, config: {} }), { ok: true, skipped: true, reason: "timescale not configured" });
});

test("fdd: engine timescale with only a string option reaches the engine as an object; unset names the option", async () => {
  let seen;
  const createEngine = async (o) => { seen = o; return engineStub(); };
  await fdd.runFdd({ sdk: { http: nfOver(MODEL_994), logEvent() {} }, config: { engine: "timescale", timescale: JSON.stringify(PG), windowHours: "12" }, pack: PACK, createEngine, now: NOW });
  assert.equal(seen.kind, "timescale");
  assert.deepEqual(seen.config, PG);
  // engine auto + the option set = timescale (an unset engine option is dropped as blank)
  await fdd.runFdd({ sdk: { http: nfOver(MODEL_994), logEvent() {} }, config: { engine: "", timescale: JSON.stringify(PG) }, pack: PACK, createEngine, now: NOW });
  assert.equal(seen.kind, "timescale");
  // the real engine factory with the engine selected and nothing set: the one clear message
  await assert.rejects(fdd.runFdd({ sdk: { http: nfOver(MODEL_994), logEvent() {} }, config: { engine: "timescale" }, pack: PACK, now: NOW }),
    /Timescale connection settings not found.*app option "timescale"/);
});


test("weather queryLayer: missing layer -> []; later-page failure propagates (Lite + full)", async () => {
  const missing = { post: async () => { throw Object.assign(new Error("HTTP 404"), { status: 404 }); } };
  // siteFromModel uses queryLayer; a missing model+site layer yields null (not a throw)
  assert.equal(await liteWeather.siteFromModel(missing), null);
  assert.equal(await weather.siteFromModel(missing), null);

  // first page OK, second page throws: must NOT look like "no site"
  let n = 0;
  const laterFail = {
    post: async (_path, body) => {
      n += 1;
      if ((body.pageOffset || 0) === 0) {
        return { data: { points: filler("p", 500), totalCount: "600" } };
      }
      throw Object.assign(new Error("HTTP 503 page 2"), { status: 503 });
    },
  };
  await assert.rejects(liteWeather.siteFromModel(laterFail), /HTTP 503 page 2/);
  n = 0;
  await assert.rejects(weather.siteFromModel(laterFail), /HTTP 503 page 2/);
});

test("weather: MODEL_LOOKUP_TIMEOUT_MS is longer than WRITE_TIMEOUT_MS (paginated model)", () => {
  const { fileURLToPath } = require("node:url");
  const { dirname, join } = require("node:path");
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rel of ["../hooks/weather.js", "../../lite/hooks/open_meteo_weather.js"]) {
    const src = readFileSync(join(here, rel), "utf8");
    assert.match(src, /MODEL_LOOKUP_TIMEOUT_MS\s*=\s*45000/);
    assert.match(src, /withDeadline\(siteFromModel\([^)]*\),\s*MODEL_LOOKUP_TIMEOUT_MS/);
  }
});

// ---- 5. weather coordinates: config -> (app setting) -> NF Sites -> modeled site ----------------------------------
function withOpenMeteo(fn) {
  return async () => {
    const https = (await import("node:https")).default;
    const orig = https.get;
    const urls = [];
    https.get = (u, opts, cb) => {
      urls.push(u);
      const res = new EventEmitter(); res.statusCode = 200; res.setEncoding = () => {};
      const req = new EventEmitter(); req.setTimeout = () => {}; req.destroy = () => {};
      setImmediate(() => { cb(res); res.emit("data", JSON.stringify({ current: { time: "t", temperature_2m: 50, relative_humidity_2m: 40, dew_point_2m: 27 } })); res.emit("end"); });
      return req;
    };
    try { await fn(urls); } finally { https.get = orig; }
  };
}
const wxHttp = ({ sites = [], model = [] } = {}) => ({
  calls: [],
  async get(p) { this.calls.push(p); return { data: { sites } }; },
  async post(p, body) {
    if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? model : [] } };
    if (p === "/api/v1/point/data") return { data: { success: true } };
    throw new Error("unexpected " + p);
  },
});
const vars = { byLabel: (l) => ({ uuid: "u-" + l, write: async () => {} }) };

test("weather: coordinates from the app options (strings) beat NF Sites and the model, and the source says so",
  withOpenMeteo(async (urls) => {
    const http = wxHttp({ sites: [{ id: "x", latitude: 10, longitude: 20 }], model: [{ pointType: "SITE", name: "m", attrs: { id: "m", latitude: 30, longitude: 40 } }] });
    const out = await weather({ globalVariables: vars, sdk: { http, logEvent() {} }, config: { latitude: "43.0731", longitude: "-89.4012", engine: "timescale" } });
    assert.match(urls[0], /latitude=43\.0731&longitude=-89\.4012/);
    assert.match(out.coords_source, /app setting/);
    assert.deepEqual(http.calls, [], "no Sites call when the settings have coordinates");
  }));

test("weather: blank app options fall through to NF Sites, then to the modeled site",
  withOpenMeteo(async (urls) => {
    const a = await weather({ globalVariables: vars, sdk: { http: wxHttp({ sites: [{ id: "s", latitude: 10, longitude: 20 }] }), logEvent() {} }, config: { latitude: "", longitude: "" } });
    assert.equal(a.coords_source, "nf sites api");
    const b = await weather({ globalVariables: vars, sdk: { http: wxHttp({ sites: [{ id: "s", latitude: 0, longitude: 0 }], model: [{ pointType: "SITE", name: "m", attrs: { id: "m", latitude: 30, longitude: 40 } }] }), logEvent() {} }, config: {} });
    assert.match(b.coords_source, /haystack model/);
    assert.equal(urls.length, 2);
  }));

test("weather: no coordinates anywhere names every place to set them; bad option values are rejected by name", async () => {
  const http = wxHttp({});
  await assert.rejects(weather({ globalVariables: vars, sdk: { http, logEvent() {} }, config: {} }),
    /no NF site has latitude\/longitude.*set the app options "latitude" and "longitude"/);
  assert.equal(weather.coordsFromConfig({}), null);
  assert.equal(weather.coordsFromConfig({ latitude: "", longitude: "" }), null);
  assert.equal(weather.coordsFromConfig({ latitude: 0, longitude: "0" }), null, "0,0 = an unfilled option");
  for (const bad of [{ latitude: "43" }, { latitude: "abc", longitude: "1" }, { latitude: 91, longitude: 1 }]) {
    assert.throws(() => weather.coordsFromConfig(bad), /app options "latitude" and "longitude"/, JSON.stringify(bad));
  }
  assert.equal(weather.coordsFromConfig({ latitude: 1, longitude: 2, site: "mine" }).id, "mine");
});

test("weather: more than one page of sites is read (the located site is on page 2)",
  withOpenMeteo(async (urls) => {
    const sites = [...Array.from({ length: 600 }, (_, i) => ({ id: `n${i}`, latitude: 0, longitude: 0 })), { id: "late", latitude: 12, longitude: 34 }];
    const http = { async get(u) { const q = new URL(u, "http://x").searchParams; const off = Number(q.get("pageOffset")) || 0; return { data: { sites: sites.slice(off, off + 500), totalCount: String(sites.length) } }; }, post: async () => ({ data: { success: true } }) };
    const out = await weather({ globalVariables: vars, sdk: { http, logEvent() {} }, config: {} });
    assert.equal(out.site, "late");
    assert.match(urls[0], /latitude=12&longitude=34/);
  }));
