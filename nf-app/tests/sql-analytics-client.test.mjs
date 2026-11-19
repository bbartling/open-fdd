// #1649: the browser's SQL analytics go through the analytics hook (tool sql_grid). The round trip
// (static/sql-analytics-client.js -> JSON -> hooks/analytics.js sql_grid -> hooks/lib/sql-analytics.js -> JSON -> client)
// must answer exactly what the in-process call answers, Maps and all.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const SA = require("../hooks/lib/sql-analytics.js");
const wire = require("../static/sql-analytics-client.js");
const hook = require("../hooks/analytics.js");
const H = 3600000, T0 = Date.UTC(2026, 2, 2);   // a Monday

function grid() {
  const t = [], cols = { fan: [], oa_t: [], rat: [], mat: [], damper: [], sat: [], ch: [], bas: [], web: [] };
  for (let i = 0; i < 12 * 24 * 9; i++) {
    const x = T0 + i * 300000, h = ((x - T0) / H) % 24, oat = 12 + 10 * Math.sin(((h - 9) / 24) * 2 * Math.PI);
    const on = h >= 6 && h < 18 ? 1 : 0, dmp = oat < 18 ? 80 : 20;
    t.push(x);
    cols.fan.push(on); cols.oa_t.push(i % 3 ? null : oat); cols.rat.push(22); cols.mat.push(22 + (dmp / 100) * (oat - 22) + 0.3);
    cols.damper.push(dmp); cols.sat.push(13); cols.ch.push(oat > 18 ? 1 : 0);
    cols.bas.push(oat + 0.7); cols.web.push(i % 12 ? null : oat);
  }
  return { t, cols };
}

// the hook answers through sdk.logEvent and its return value; the client gets the JSON text, as from NF's runs API
const viaHook = wire.makeClient(async (args) => {
  for (const v of Object.values(args)) assert.equal(typeof v, "string");   // NF StartHook args: flat string map
  let logged = null;
  const ans = await hook.handle({ sdk: { logEvent: (m) => { logged = m; } }, args });
  assert.deepEqual(JSON.parse(logged), ans);
  return JSON.parse(logged);
});

test("wire: grid encode / decode is lossless and run-length compresses status columns", () => {
  const g = grid(), w = wire.encodeGrid(g);
  assert.deepEqual(w.t, { t0: T0, step: 300000, n: g.t.length });
  assert.ok(w.cols.fan.length < 20 && w.cols.rat.length === 1);
  assert.deepEqual(wire.decodeGrid(JSON.parse(JSON.stringify(w))), g);
  const odd = { t: [1, 2, 4], cols: { a: [1, null, NaN] } };
  assert.deepEqual(wire.decodeGrid(wire.encodeGrid(odd)), { t: [1, 2, 4], cols: { a: [1, null, null] } });
});

test("runtime / mech / econ / bas through the hook equal the in-process SQL", async () => {
  const g = grid();
  const weekOf = (x) => x - ((x - T0) % (7 * 24 * H));
  const occ = (x) => { const h = ((x - T0) / H) % 24; return h >= 7 && h < 17; };
  const rspecs = [{ key: "AHU-1", motor: "fan", oat: "oa_t", weekOf, occ }, { key: "AHU-2", motor: "ch", oat: null, weekOf }];
  const direct = await SA.runtimeFromGrid("sqlite", g, rspecs);
  const remote = await viaHook.runtime(g, rspecs);
  assert.ok(remote instanceof Map && remote.get("AHU-1") instanceof Map);
  assert.deepEqual(remote, direct);
  assert.ok(direct.get("AHU-1").size === 2 && direct.get("AHU-1").get(T0).inHours > 0);

  const mspecs = [{ key: "CH-1", proof: "ch", oat: "oa_t" }];
  assert.deepEqual(await viaHook.mech(g, mspecs), await SA.mechFromGrid("sqlite", g, mspecs));

  const eg = { t: g.t, cols: { fan: g.cols.fan, oa_t: g.cols.oa_t, rat: g.cols.rat, mat: g.cols.mat, damper: g.cols.damper, sat: g.cols.sat } };
  const econ = await viaHook.econ(eg);
  assert.deepEqual(econ, await SA.econFromGrid("sqlite", eg));
  assert.ok(econ.rows.length > 0 && econ.summary.n > 0);

  const bg = { t: g.t, cols: { bas: g.cols.bas, web: g.cols.web } };
  const bas = await viaHook.bas(bg);
  assert.deepEqual(bas, await SA.basFromGrid("sqlite", bg));
  assert.ok(Math.abs(bas.stats.bias - 0.7) < 0.5 && bas.rows.length === bas.stats.n);
});

test("sql_grid refuses a bad kind or grid; the client turns that into an error", async () => {
  const bad = await hook.handle({ sdk: { logEvent: () => {} }, args: { tool: "sql_grid", kind: "oracle", grid: "{\"t\":[],\"cols\":{}}" } });
  assert.equal(bad.ok, false);
  assert.match(bad.error, /kind must be/);
  const junk = await hook.handle({ sdk: { logEvent: () => {} }, args: { tool: "sql_grid", kind: "econ", grid: "nope" } });
  assert.match(junk.error, /not JSON/);
  const c = wire.makeClient(async () => ({ ok: false, error: "boom" }));
  await assert.rejects(c.econ({ t: [1], cols: {} }), /SQL analytics \(econ\) failed: boom/);
});

test("browser: the script defines ofddSqlAnalytics on the NF api, and leaves a host's own one alone", async () => {
  const src = readFileSync(new URL("../static/sql-analytics-client.js", import.meta.url), "utf8");
  const calls = [];
  const ctx = vm.createContext({ setTimeout, location: { pathname: "/apps/static/open-fdd/index.html" },
    api: async (p, body) => {
      calls.push([p, body]);
      if (body) return { pid: 7 };
      const ans = await hook.handle({ sdk: { logEvent: () => {} }, args: calls[0][1] });
      return { runs: [{ pid: 7, state: "STATE_SUCCESS", results: { a: { events: [{ message: JSON.stringify(ans) }] } } }] };
    } });
  vm.runInContext(src, ctx);
  assert.equal(typeof ctx.ofddSqlAnalytics.econ, "function");
  const bg = { t: [T0, T0 + H, T0 + 2 * H], cols: { bas: [10, 11, 12], web: [9, null, 10] } };
  const r = await ctx.ofddSqlAnalytics.bas(bg);
  assert.equal(calls[0][0], "/api/v1/apps/open-fdd/hooks/analytics");
  assert.match(calls[1][0], /hooks\/analytics\/runs\?/);
  assert.deepEqual(JSON.parse(JSON.stringify(r)), await SA.basFromGrid("sqlite", bg));
  const own = { mine: true };
  const ctx2 = vm.createContext({ api: async () => ({}), ofddSqlAnalytics: own });
  vm.runInContext(src, ctx2);
  assert.equal(ctx2.ofddSqlAnalytics, own);
});
