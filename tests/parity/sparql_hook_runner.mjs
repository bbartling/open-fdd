// The sparql-data and rdf hooks over a synthetic NF (the SPARQL-client leg of the parity harness, tests/parity/sparql_leg.py).
// stdin: one JSON line {records, series: {uuid: [[ms, value]]}, cap}, then one JSON line per call {hook, args} where args is
// the flat string map NF StartHook delivers. stdout: one JSON line per call, the hook's answer (or {ok:false, error}).
// Only the NF HTTP surface is mocked (point/query, point/data with raw samples); query, prefixes, Turtle, Oxigraph worker,
// point selection, paging, byte cap and the NF sample-cap split are the shipped hook code.
import { createInterface } from "node:readline";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hooks = { "sparql-data": require("../../nf-app/hooks/sparql_data.js"), rdf: require("../../nf-app/hooks/rdf.js") };

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
    else out = await hooks[msg.hook]({ sdk: world.sdk, args: msg.args, config: {} });
  } catch (e) {
    out = { ok: false, error: String((e && e.message) || e), error_code: (e && e.code) || null };
  }
  process.stdout.write(JSON.stringify(out) + "\n");
}