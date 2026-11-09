// Deploy-bug fixes: weather coordinates from the modeled site, history skip, engine fallback.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const weather = require("../hooks/weather.js");
const liteWeather = require("../../lite/hooks/open_meteo_weather.js");
const history = require("../hooks/history.js");
const fdd = require("../hooks/fdd.js");

/** Fake NF point/query: records per layer; a layer not listed fails like an unknown layer. */
const fakeHttp = (layers) => ({
  async post(p, body) {
    assert.equal(p, "/api/v1/point/query");
    if (!(body.layer in layers)) throw new Error("HTTP 404");
    return { data: { points: layers[body.layer] } };
  },
});
const site = (attrs, extra = {}) => ({ pointType: "SITE", name: attrs.id, attrs, ...extra });

for (const [name, mod] of [["full", weather], ["lite", liteWeather]]) {
  test(`weather (${name}): pickSite failures that can fall back are flagged noCoords`, () => {
    const err = (fn) => { try { fn(); } catch (e) { return e; } };
    assert.equal(err(() => mod.pickSite([]))?.noCoords, true);
    assert.equal(err(() => mod.pickSite([{ id: "a", latitude: 0, longitude: 0 }], "a"))?.noCoords, true);
    assert.equal(err(() => mod.pickSite([{ id: "a", latitude: 1, longitude: 2 }, { id: "b", latitude: 3, longitude: 4 }]))?.noCoords, undefined);
  });

  test(`weather (${name}): coordinates from the modeled SITE latitude/longitude`, async () => {
    const s = await mod.siteFromModel(fakeHttp({ model: [site({ id: "s1", latitude: "43.07", longitude: "-89.4" })] }));
    assert.equal(s.id, "s1");
    assert.equal(s.latitude, 43.07);
    assert.equal(s.longitude, -89.4);
    assert.match(s.source, /model/);
  });

  test(`weather (${name}): geoCoord "C(lat,lon)" and the site layer are read; nothing is invented`, async () => {
    const g = await mod.siteFromModel(fakeHttp({ model: [site({ id: "s1", geoCoord: "C(40.5,-75.25)" })], site: [] }));
    assert.deepEqual([g.latitude, g.longitude], [40.5, -75.25]);
    // model SITE has no coordinates; the site layer record does
    const l = await mod.siteFromModel(fakeHttp({ model: [site({ id: "s1" })], site: [{ name: "s1", attrs: { id: "s1", latitude: 10, longitude: 20 } }] }));
    assert.deepEqual([l.latitude, l.longitude], [10, 20]);
    assert.match(l.source, /site layer/);
    // none anywhere, 0,0 and a missing site layer: null
    assert.equal(await mod.siteFromModel(fakeHttp({ model: [site({ id: "s1" }), site({ id: "s2", latitude: 0, longitude: 0 })] })), null);
    assert.equal(await mod.siteFromModel(fakeHttp({ model: [site({ id: "s1", latitude: "", longitude: "" })] })), null);
  });

  test(`weather (${name}): several modeled sites need config site; config site picks one`, async () => {
    const layers = { model: [site({ id: "a", latitude: 1, longitude: 2 }), site({ id: "b", latitude: 3, longitude: 4 })] };
    await assert.rejects(mod.siteFromModel(fakeHttp(layers)), /set the app config value "site"/);
    assert.equal((await mod.siteFromModel(fakeHttp(layers), "b")).latitude, 3);
    assert.equal(await mod.siteFromModel(fakeHttp(layers), "zzz"), null);
  });
}

test("weather (full): hook falls back to the model site when /api/v1/sites has none, and records the source", async () => {
  const written = [];
  const http = {
    async get(p) { assert.match(p, /^\/api\/v1\/sites/); return { data: { sites: [{ id: "x", latitude: 0, longitude: 0 }] } }; },
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? [site({ id: "s1", latitude: 43.07, longitude: -89.4 })] : [] } };
      if (p === "/api/v1/point/data") { written.push(body); return { data: { success: true } }; }
      throw new Error("unexpected " + p);
    },
  };
  const orig = (await import("node:https")).default.get;
  const https = (await import("node:https")).default;
  let url = "";
  https.get = (u, opts, cb) => {
    url = u;
    const { EventEmitter } = require("node:events");
    const res = new EventEmitter(); res.statusCode = 200; res.setEncoding = () => {};
    const req = new EventEmitter(); req.setTimeout = () => {}; req.destroy = () => {};
    setImmediate(() => { cb(res); res.emit("data", JSON.stringify({ current: { time: "t", temperature_2m: 50, relative_humidity_2m: 40, dew_point_2m: 27 } })); res.emit("end"); });
    return req;
  };
  try {
    const vars = { byLabel: (l) => ({ uuid: "u-" + l, write: async () => {} }) };
    const out = await weather({ globalVariables: vars, sdk: { http, logEvent() {} }, config: {} });
    assert.match(url, /latitude=43\.07&longitude=-89\.4/);
    assert.equal(out.site, "s1");
    assert.match(out.coords_source, /model/);
    assert.equal(written.length, 3);
  } finally {
    https.get = orig;
  }
});

test("weather (full): no coordinates anywhere keeps the clear error", async () => {
  const http = {
    async get() { return { data: { sites: [] } }; },
    async post() { return { data: { points: [site({ id: "s1" })] } }; },
  };
  await assert.rejects(weather({ globalVariables: {}, sdk: { http }, config: {} }), /no NF site has latitude\/longitude/);
});

test("history: no config.timescale and no args is a structured skip (success)", async () => {
  const logs = [];
  const r = await history({ sdk: { logEvent: (m) => logs.push(m) }, args: {}, config: {} });
  assert.deepEqual(r, { ok: true, skipped: true, reason: "timescale not configured" });
  assert.deepEqual(await history({ sdk: {}, config: {} }), r, "no args field at all");
});

test("history: no config.timescale but args that ask for a query still fails", async () => {
  await assert.rejects(history({ sdk: {}, args: { uuids: ["u1"], from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" }, config: {} }),
    /Timescale connection settings not found.*app option \"timescale\"/);
});

const bigBox = { async get() { return { data: { resources: [{ memory: { totalBytes: String(16 * 1024 ** 3) } }] } }; } };

test("engine auto: pglite on a big box when installed, sqlite fallback (with a note) when not", async () => {
  assert.deepEqual(await fdd.pickEngine(bigBox, "auto", undefined, () => true), { kind: "pglite", note: "" });
  const fb = await fdd.pickEngine(bigBox, undefined, undefined, () => false);
  assert.equal(fb.kind, "sqlite");
  assert.match(fb.note, /pglite is not installed/);
});

test("engine: an explicitly configured engine is never swapped", async () => {
  assert.deepEqual(await fdd.pickEngine(bigBox, "pglite", undefined, () => false), { kind: "pglite", note: "" });
  assert.deepEqual(await fdd.pickEngine(bigBox, "sqlite", undefined, () => true), { kind: "sqlite", note: "" });
  assert.equal((await fdd.pickEngine(bigBox, "auto", { host: "h" }, () => false)).kind, "timescale");
});

test("history: normalizeArgs coerces StartHook string-map uuids and windowHours", async () => {
  const a = history.normalizeArgs({ uuids: '["u-1","u-2"]', windowHours: "1" });
  assert.deepEqual(a.uuids, ["u-1", "u-2"]);
  assert.ok(typeof a.from === "string" && typeof a.to === "string");
  const spanMs = Date.parse(a.to) - Date.parse(a.from);
  assert.ok(Math.abs(spanMs - 3600_000) < 5000, `window ~1h, got ${spanMs}`);
  assert.deepEqual(history.normalizeArgs({ uuids: ["u-9"], from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" }).uuids, ["u-9"]);
});

test("history: StartHook argument context shares typed and string-map normalization", () => {
  const nfArgs = history.normalizeArgs(history.argsOf({ args: { uuids: '["u-1","u-2"]', windowHours: "2" } }));
  assert.deepEqual(nfArgs.uuids, ["u-1", "u-2"]);
  assert.equal(typeof nfArgs.windowHours, "number");
  assert.ok(Math.abs((Date.parse(nfArgs.to) - Date.parse(nfArgs.from)) - 2 * 3600_000) < 10);
  const typed = history.normalizeArgs(history.argsOf({ args: { uuids: ["u-3"], windowHours: 1, bucket: "1 day" } }));
  assert.deepEqual(typed.uuids, ["u-3"]);
  assert.equal(typed.bucket, "1 day");
  assert.equal(typeof history.normalizeArgs({ uuids: "not-json" }).uuids, "string", "invalid JSON stays for validation");
});

