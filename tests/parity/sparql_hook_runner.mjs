// The sparql-data and rdf hooks over a synthetic NF (the SPARQL-client leg of the parity harness, tests/parity/sparql_leg.py).
// stdin: one JSON line {records, series: {uuid: [[ms, value]]}, cap}, then one JSON line per call {hook, args} where args is
// the flat string map NF StartHook delivers. stdout: one JSON line per call, the hook's answer (or {ok:false, error}).
// Only the NF HTTP surface is mocked (point/query, point/data with raw samples); query, prefixes, Turtle, Oxigraph worker,
// point selection, paging, byte cap and the NF sample-cap split are the shipped hook code.
import { createInterface } from "node:readline";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hooks = { "sparql-data": require("../../nf-app/hooks/sparql_data.js"), rdf: require("../../nf-app/hooks/rdf.js") };
const tsLib = require("../../nf-app/hooks/lib/timescale.js");
const UNIT = { second: 1, minute: 60, hour: 3600, day: 86400, week: 604800 };

/**
 * Timescale-selected source (#1618, 5.0.20): the shipped hook and the shipped lib/timescale.js historyRoute (bounds,
 * coverage, byte cap, row shaping) run unchanged; only the database is replaced by an in-memory
 * openfdd.history_buckets: time_bucket aligned to the Unix epoch, avg/min/max/count of the numeric samples in
 * [from, to), ordered by point then bucket. NF text samples have no Timescale value, exactly like the connector.
 */
function fakePg(w) {
  return {
    end: async () => {},
    query: async (sql, params = []) => {
      if (!/openfdd\.history_buckets/.test(sql)) return { rows: [] };
      const [ids, from, to, width, limit] = params;
      const m = /^(\d+)\s+(second|minute|hour|day|week)s?$/i.exec(String(width));
      if (!m) throw new Error("fake history_buckets: bad width " + width);
      const step = Number(m[1]) * UNIT[m[2].toLowerCase()] * 1000;
      const f = Date.parse(from), t = Date.parse(to), rows = [];
      for (const id of [...ids].sort()) {
        const acc = new Map();
        for (const [ts, v] of w.series[id] || []) {
          if (ts < f || ts >= t || typeof v !== "number" || !Number.isFinite(v)) continue;
          const b = Math.floor(ts / step) * step;
          const a = acc.get(b) || { sum: 0, n: 0, min: Infinity, max: -Infinity };
          a.sum += v; a.n += 1; a.min = Math.min(a.min, v); a.max = Math.max(a.max, v);
          acc.set(b, a);
        }
        for (const b of [...acc.keys()].sort((x, y) => x - y)) {
          const a = acc.get(b);
          rows.push({ point_uuid: id, bucket: new Date(b), avg: a.sum / a.n, min: a.min, max: a.max, n: a.n });
        }
      }
      w.tsCalls = (w.tsCalls || 0) + 1;
      return { rows: rows.slice(0, Number(limit) || rows.length) };
    },
  };
}

let world = null;
function sdkFor(w) {
  const model = w.records.filter((r) => r.pointType !== "POINT");
  const pts = w.records.filter((r) => r.pointType === "POINT");
  const http = {
    defaults: { baseURL: "http://127.0.0.1:8080" },
    post: async (url, body) => {
      if (url !== "/api/v1/point/query") throw new Error("unexpected POST " + url);
      const all = body.layer === "model" ? model : pts;
      const size = Number(body.pageSize || all.length) || all.length, off = Number(body.pageOffset || 0);
      const page = body.pageSize ? all.slice(off, off + size) : all;
      return { data: { points: page, totalCount: all.length } };
    },
    get: async (url) => {
      const u = new URL("http://x" + url);
      if (u.pathname !== "/api/v1/point/data") throw new Error("unexpected GET " + url);
      if (u.searchParams.get("window")) throw new Error("the parity leg reads raw samples");
      const from = Date.parse(u.searchParams.get("from")), to = Date.parse(u.searchParams.get("to"));
      const data = u.searchParams.getAll("uuids").map((id) => ({
        uuid: id,
        values: (w.series[id] || []).filter(([t]) => t >= from && t < to).slice(0, w.cap || 10000)
          .map(([t, v]) => (typeof v === "string" ? { ts: new Date(t).toISOString(), string: v } : { ts: new Date(t).toISOString(), double: v })),
      }));
      return { data: { data } };
    },
  };
  return { http, logEvent: () => {} };
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity, terminal: false });
for await (const line of rl) {
  if (!line.trim()) continue;
  let out;
  try {
    const msg = JSON.parse(line);
    if (!world) { world = msg; world.sdk = sdkFor(world); out = { ok: true, loaded: world.records.length }; }
    else if (msg.hook === "sparql-data" && world.timescale) {
      out = await hooks["sparql-data"].handle({ sdk: world.sdk, args: msg.args, config: { timescale: { host: "parity-fake" } },
        deps: { ts: { connect: async () => fakePg(world), historyRoute: tsLib.historyRoute } } });
    } else out = await hooks[msg.hook]({ sdk: world.sdk, args: msg.args, config: {} });
  } catch (e) {
    out = { ok: false, error: String((e && e.message) || e), error_code: (e && e.code) || null };
  }
  process.stdout.write(JSON.stringify(out) + "\n");
}