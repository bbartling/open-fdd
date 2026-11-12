// node --test nf-app/tests/weather-options.test.mjs
// #1552: the shared weather hook (both editions): the `weather` off switch (no HTTP at all), the exporters list and the
// offline (fetch fails) case. Open-Meteo is stubbed through the https module the hook captured at load time.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { EventEmitter } from "node:events";

const require = createRequire(import.meta.url);
const https = require("https");
const settings = require("../hooks/lib/settings.js");
const EDITIONS = { full: require("../hooks/weather.js"), lite: require("../../lite/hooks/open_meteo_weather.js") };

/** https.get stand-in: counts requests; `mode` ok | fail (network error) | http500. Returns a restore function. */
function stubOpenMeteo(mode = "ok") {
  const orig = https.get;
  const seen = { n: 0, urls: [] };
  https.get = (url, opts, cb) => {
    seen.n++; seen.urls.push(String(url));
    const req = new EventEmitter();
    req.setTimeout = () => {}; req.destroy = (e) => { if (e) setImmediate(() => req.emit("error", e)); };
    setImmediate(() => {
      if (mode === "fail") { req.emit("error", new Error("getaddrinfo ENOTFOUND api.open-meteo.com")); return; }
      const res = new EventEmitter(); res.statusCode = mode === "http500" ? 500 : 200; res.setEncoding = () => {};
      cb(res);
      res.emit("data", JSON.stringify({ current: { time: "2026-01-01T00:00", temperature_2m: 50, relative_humidity_2m: 60, dew_point_2m: 36.3 } }));
      res.emit("end");
    });
    return req;
  };
  return Object.assign(seen, { restore: () => { https.get = orig; } });
}

/** sdk.http that logs every call; `bacnet`: whether NF's BACnet server answers. */
function fakeNf({ bacnet = true } = {}) {
  const calls = [];
  const http = {
    async get(url) {
      calls.push(`GET ${url}`);
      if (url.startsWith("/api/v1/sites")) return { data: { sites: [{ id: "s1", name: "Site One", latitude: 40.5, longitude: -75.25 }] } };
      if (url === "/api/v1/bacnet/configuration") { if (!bacnet) throw Object.assign(new Error("not found"), { status: 404 }); return { data: { deviceInstance: 1 } }; }
      if (url === "/api/v1/bacnet/local") return { data: { objects: [] } };
      throw new Error("unexpected GET " + url);
    },
    async post(url, body) { calls.push(`POST ${url}`); return { data: { success: true } }; },
    async patch(url) { calls.push(`PATCH ${url}`); return { data: {} }; },
  };
  return { http, calls };
}
const vars = { byLabel: (label) => ({ uuid: `u-${label}` }) };
const run = (hook, nf, config) => hook({ globalVariables: vars, sdk: { http: nf.http, logEvent() {} }, config });
const writes = (nf) => nf.calls.filter((c) => c === "POST /api/v1/point/data").length;

for (const [edition, hook] of Object.entries(EDITIONS)) {
  test(`[${edition}] weather:false makes no outbound HTTP and no NF call; returns {skipped, reason: "weather disabled"}`, async () => {
    for (const config of [{ weather: false }, { weather: "false" }, { weatherEnabled: false }, { weather: "off" }, { weather: true, weatherEnabled: false }]) {
      const om = stubOpenMeteo(), nf = fakeNf();
      try {
        const out = await run(hook, nf, config);
        assert.deepEqual(out, { skipped: true, reason: "weather disabled" }, JSON.stringify(config));
        assert.equal(om.n, 0, "no Open-Meteo request");
        assert.deepEqual(nf.calls, [], "no NF call either");
      } finally { om.restore(); }
    }
  });

  test(`[${edition}] weather on (default, true, or blank) runs as before`, async () => {
    for (const config of [{}, { weather: true }, { weather: "" }, { weatherEnabled: "true" }]) {
      const om = stubOpenMeteo(), nf = fakeNf();
      try {
        const out = await run(hook, nf, config);
        assert.equal(om.n, 1, JSON.stringify(config));
        assert.equal(out.site, "s1");
        assert.equal(writes(nf), 3);
        assert.deepEqual(Object.keys(out.bacnet), ["av.1", "av.2", "av.3"]);
        assert.equal(out.exporters["bacnet-av"].status, "ok");
      } finally { om.restore(); }
    }
  });

  test(`[${edition}] offline: the fetch fails, the run fails, nothing is written or exported`, async () => {
    for (const mode of ["fail", "http500"]) {
      const om = stubOpenMeteo(mode), nf = fakeNf();
      try {
        await assert.rejects(run(hook, nf, {}), mode === "fail" ? /ENOTFOUND/ : /HTTP 500/);
        assert.equal(writes(nf), 0);
        assert.ok(!nf.calls.some((c) => c.includes("/bacnet/local")), nf.calls.join(" | "));
      } finally { om.restore(); }
    }
  });

  test(`[${edition}] BACnet server absent: the default exporter is skipped with its reason; variables are still written`, async () => {
    const om = stubOpenMeteo(), nf = fakeNf({ bacnet: false });
    try {
      const out = await run(hook, nf, {});
      assert.equal(writes(nf), 3);
      assert.equal(out.bacnet, null);
      assert.equal(out.exporters["bacnet-av"].status, "skipped");
      assert.match(out.exporters["bacnet-av"].reason, /BACnet server is not present/);
      assert.ok(!nf.calls.some((c) => c.includes("/bacnet/local")));
    } finally { om.restore(); }
  });

  test(`[${edition}] an exporter asked for by name that is absent fails the run, after the variables were written`, async () => {
    for (const config of [{ exporters: "bacnet-av" }, { exporters: ["bacnet-av"] }, { exporters: '["bacnet-av"]' }, { bacnetMirror: true }]) {
      const om = stubOpenMeteo(), nf = fakeNf({ bacnet: false });
      try {
        await assert.rejects(run(hook, nf, config), /weather values written, but 1 exporter\(s\) failed: bacnet-av: .*not present/, JSON.stringify(config));
        assert.equal(writes(nf), 3, "variables were written first");
      } finally { om.restore(); }
    }
  });

  test(`[${edition}] exporters "none" / bacnetMirror:false = hook variables only, and BACnet is not even probed`, async () => {
    for (const config of [{ exporters: "none" }, { exporters: "[]" }, { bacnetMirror: false }, { bacnet_mirror: "false" }]) {
      const om = stubOpenMeteo(), nf = fakeNf();
      try {
        const out = await run(hook, nf, config);
        assert.equal(writes(nf), 3);
        assert.deepEqual(out.exporters, {}, JSON.stringify(config));
        assert.ok(!nf.calls.some((c) => c.includes("/bacnet/")), nf.calls.join(" | "));
      } finally { om.restore(); }
    }
  });

  test(`[${edition}] an unknown exporter id is rejected before any network call`, async () => {
    const om = stubOpenMeteo(), nf = fakeNf();
    try {
      await assert.rejects(run(hook, nf, { exporters: "modbus-tcp" }), /unknown weather exporter\(s\) modbus-tcp; known: bacnet-av/);
      assert.equal(om.n, 0);
      assert.deepEqual(nf.calls, []);
    } finally { om.restore(); }
  });

  test(`[${edition}] a registered exporter gets the values; a failing one fails the run after the others ran`, async () => {
    const got = [];
    hook.registerExporter({ id: "test-sink", async detect() { return { available: true }; }, async export(sdk, ctx) { got.push(ctx.values); return { sent: 3 }; } });
    hook.registerExporter({ id: "test-broken", async detect() { return { available: true }; }, async export() { throw new Error("sink down"); } });
    const om = stubOpenMeteo(), nf = fakeNf();
    try {
      const out = await run(hook, nf, { exporters: "test-sink" });
      assert.equal(out.exporters["test-sink"].status, "ok");
      assert.deepEqual(Object.keys(got[0]), ["oa_dry_bulb_web", "oa_rh_web", "oa_dewpoint_web"]);
      assert.equal(out.bacnet, null, "bacnet-av was not named: not run");
      await assert.rejects(run(hook, fakeNf(), { exporters: "test-broken,test-sink" }), /test-broken: sink down/);
      assert.equal(got.length, 2, "the other exporter still ran");
    } finally { om.restore(); delete hook.EXPORTERS["test-sink"]; delete hook.EXPORTERS["test-broken"]; }
  });
}

test("settings.weatherEnabled: default on, either option false = off", () => {
  assert.equal(settings.weatherEnabled({}), true);
  assert.equal(settings.weatherEnabled(null), true);
  assert.equal(settings.weatherEnabled(settings.normalizeConfig({ weather: "false" })), false);
  assert.equal(settings.weatherEnabled(settings.normalizeConfig({ weatherEnabled: { boolean: false } })), false);
  assert.equal(settings.weatherEnabled(settings.normalizeConfig({ weather: "true", weatherEnabled: "no" })), false);
  assert.equal(settings.weatherEnabled(settings.normalizeConfig({ weather: "" })), true, "blank = not set");
});
