#!/usr/bin/env node
// Mock Normal Framework for developing / testing the Open-FDD app on any PC (no NF box needed).
//
//   node nf-app/dev/mock-nf.mjs [port]          → http://127.0.0.1:8765/api/v1/apps/static/open-fdd/
//
// Serves nf-app/static at the NF app URL and answers the NF API calls the app makes
// (point/query, point/data with server-side resampling, platform/info, bacnet/*, hook runs)
// from a synthetic two-site building: AHUs, VAVs, a chiller plant + tower, a boiler, electric
// meters, a weather station, and FDD hook result points with some faults. Points are built
// from fdd-catalog.json roles (NF class + Haystack markers), exactly how a real site is tagged,
// so every RCx/FDD view binds. Deterministic: same data every run. Read-only; nothing to break.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.join(HERE, "..", "static");
const APP_PREFIX = "/api/v1/apps/static/open-fdd/";
const PORT = Number(process.argv[2]) || 8765;
const catalog = JSON.parse(fs.readFileSync(path.join(STATIC, "fdd-catalog.json"), "utf8"));
const DAYS = 8;
const NOW = Math.floor(Date.now() / 300e3) * 300e3;
const START = NOW - DAYS * 86400e3;

// ---- synthetic signals (°F, %, inH₂O, cfm, kW) -------------------------------------------
const H = (t) => ((t / 3600e3) % 24 + 24) % 24;                 // UTC hour (fine for a mock)
const day = (t) => Math.floor(t / 86400e3);
const occ = (t) => { const h = H(t), d = new Date(t).getUTCDay(); return d > 0 && d < 6 && h >= 12 && h < 23 ? 1 : 0; };
const wave = (t, period, phase = 0) => Math.sin((2 * Math.PI * (t / 3600e3 + phase)) / period);
const noise = (t, seed) => { const x = Math.sin(t / 3e5 * 12.9898 + seed * 78.233) * 43758.5453; return x - Math.floor(x) - 0.5; };
const oat = (t) => 58 + 14 * wave(t, 24, -9) + 6 * wave(t, 24 * 5) + noise(t, 1);

/** value(t) for a role on an equip index i (variety across equips). */
function signal(role, i, t) {
  const o = occ(t), n = (s) => noise(t, s + i * 7);
  switch (role) {
    case "oa_t": return oat(t) + 1.5 + n(2);                       // BAS sensor reads a bit warm
    case "web_oa_t": return Math.round(oat(t) * 10) / 10;
    case "web_oa_dp": return oat(t) - 12 + n(3);
    case "web_wb_t": return oat(t) - 6 + n(4);
    case "oa_h": return 55 + 20 * wave(t, 24, 3) + n(5) * 4;
    case "rat": return 72 + n(6) + (o ? 1 : -2);
    case "sat": return o ? 55 + (i === 1 ? 4 : 0) + n(7) : 68 + n(7);   // AHU-2 runs warm (SATDEV)
    case "sat_sp": return o ? 55 : 65;
    case "mat": { const d = signal("oa_damper_pct", i, t) / 100; return d * oat(t) + (1 - d) * signal("rat", i, t) + n(8); }
    case "oa_damper_pct": return o ? (i === 0 && oat(t) > 70 ? 80 : Math.min(100, Math.max(15, (68 - oat(t)) * 4))) : 0;
    case "fan_cmd": return i === 1 ? 1 : o;                          // AHU-2 runs 24/7 (SCHED-247)
    case "fan_status": return signal("fan_cmd", i, t);
    case "clg_valve_pct": return o && oat(t) > 60 ? Math.min(100, (oat(t) - 60) * 5) : 0;
    case "htg_valve_pct": return o && oat(t) < 50 ? Math.min(100, (50 - oat(t)) * 5) : 0;
    case "duct_static": return o || i === 1 ? 1.2 + 0.15 * n(9) - (i === 0 ? 0.35 : 0) : 0.02;
    case "duct_static_sp": return o || i === 1 ? 1.25 : 0;
    case "zone_t": return 72 + 2.5 * wave(t, 24, i) + (i === 2 ? 4 : 0) + n(10);   // VAV-3 runs hot
    case "zone_air_temp_sp": return o ? 72 : 76;
    case "cooling_sp": return o ? 74 : 80;
    case "heating_sp": return o ? 70 : 64;
    case "zone_flow": return o ? 450 + 150 * wave(t, 6, i) + 20 * n(11) - (i === 3 ? 300 : 0) : 120;
    case "zone_airflow_sp": return o ? 450 + 150 * wave(t, 6, i) : 120;
    case "damper_pct": case "damper_cmd": return i === 2 ? 100 : o ? 40 + 30 * wave(t, 6, i) : 15;  // VAV-3 pinned open
    case "chw_supply_t": return 44 + (o ? 0 : 3) + n(12);
    case "chw_return_t": return signal("chw_supply_t", i, t) + (o ? 4 : 1.5);    // low ΔT → CHW-1
    case "chiller_status": case "chw_pump_status": case "compressor_status": case "chiller_cmd": return o && oat(t) > 55 ? 1 : 0;
    case "cw_supply_t": return 85 + n(13);
    case "cw_return_t": return 94 + n(14);
    case "tower_fan_cmd": return o && oat(t) > 60 ? 70 : 0;
    case "hw_supply_t": return 160 - (oat(t) - 40) * 0.8 + n(15);
    case "hw_return_t": return signal("hw_supply_t", i, t) - 20;
    case "pump_status": return o ? 1 : 0;
    case "electric_kw": return (i === 0 ? 220 : 140) + 160 * o + 3 * Math.max(0, oat(t) - 65) + 10 * n(16);
    case "electric_kwh": return ((t - START) / 3600e3) * ((i === 0 ? 300 : 200)) + 5 * n(17);
    default: return 50 + 10 * wave(t, 24, i) + n(18);
  }
}

const UNITS = (role) => (/(_t|_sp|temp)$/.test(role) || ["sat", "mat", "rat"].includes(role)) && !/static|airflow/.test(role) ? "°F"
  : /pct|damper|valve|_h$/.test(role) ? "%" : /static/.test(role) ? "inH₂O" : /flow/.test(role) ? "cfm"
  : role === "electric_kw" ? "kW" : role === "electric_kwh" ? "kWh" : /status|cmd$/.test(role) ? "" : "";
const isBool = (role) => /(_status|^fan_cmd|chiller_cmd)$/.test(role);

// ---- the building -----------------------------------------------------------------------
const sites = [
  { id: "site-north", dis: "North Campus Hall", area: "52000", tz: "America/Chicago", lat: 43.07, lon: -89.4 },
  { id: "site-south", dis: "South Annex", area: "31000", tz: "America/Chicago", lat: 43.05, lon: -89.42 },
];
const equips = [
  { id: "AHU-1", site: 0, markers: "equip,ahu", roles: ["sat", "sat_sp", "mat", "rat", "oa_t", "oa_damper_pct", "fan_cmd", "fan_status", "clg_valve_pct", "htg_valve_pct", "duct_static", "duct_static_sp"] },
  { id: "AHU-2", site: 0, markers: "equip,ahu", roles: ["sat", "sat_sp", "mat", "rat", "oa_t", "oa_damper_pct", "fan_cmd", "fan_status", "clg_valve_pct", "duct_static", "duct_static_sp"] },
  ...[1, 2, 3, 4].map((n) => ({ id: `VAV-${n}`, site: 0, markers: "equip,vav", roles: ["zone_t", "zone_air_temp_sp", "cooling_sp", "heating_sp", "zone_flow", "zone_airflow_sp", "damper_pct"] })),
  { id: "CH-1", site: 0, markers: "equip,chiller", roles: ["chw_supply_t", "chw_return_t", "chiller_status", "chiller_cmd", "chw_pump_status", "cw_supply_t", "cw_return_t", "compressor_status"] },
  { id: "CT-1", site: 0, markers: "equip,coolingTower", roles: ["cw_supply_t", "cw_return_t", "tower_fan_cmd"] },
  { id: "BLR-1", site: 0, markers: "equip,boiler", roles: ["hw_supply_t", "hw_return_t", "pump_status"] },
  { id: "MTR-N", site: 0, markers: "equip,meter,elecMeter", roles: ["electric_kw", "electric_kwh"] },
  { id: "RTU-S1", site: 1, markers: "equip,ahu,rtu", roles: ["sat", "sat_sp", "mat", "rat", "oa_t", "oa_damper_pct", "fan_cmd", "fan_status", "duct_static"] },
  { id: "MTR-S", site: 1, markers: "equip,meter,elecMeter", roles: ["electric_kw", "electric_kwh"] },
];
const uuidOf = (name) => {
  const h = crypto.createHash("sha1").update(`mock:${name}`).digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-5${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
};

const records = [];   // model-layer entities + default-layer points
const signals = new Map();   // uuid -> (t) => value
for (const s of sites) {
  records.push({ uuid: uuidOf(s.id), name: s.id, layer: "model", pointType: "SITE",
    attrs: { id: s.id, dis: s.dis, markers: "site", area: s.area, tz: s.tz } });
}
equips.forEach((e, ei) => {
  const site = sites[e.site].id;
  records.push({ uuid: uuidOf(e.id), name: e.id, layer: "model", pointType: "EQUIPMENT",
    attrs: { id: e.id, dis: e.id, markers: e.markers, siteRef: site } });
  const idx = equips.filter((x) => x.markers === e.markers).indexOf(e);
  for (const role of e.roles) {
    const def = catalog.roles[role];
    const uuid = uuidOf(`${e.id}/${role}`);
    records.push({ uuid, name: `${e.id} ${role}`, layer: "default", pointType: "POINT", attrs: {
      dis: `${e.id} ${def.name}`, markers: ["point", "his", ...def.markers].join(","), class: def.classes[0] || "",
      equipRef: e.id, siteRef: site, unit: UNITS(role), kind: isBool(role) ? "Bool" : "Number" } });
    signals.set(uuid, (t) => signal(role, idx, t));
  }
});
for (const s of sites) {
  for (const role of ["web_oa_t", "web_oa_dp", "web_wb_t"]) {
    const def = catalog.roles[role];
    const uuid = uuidOf(`${s.id}/${role}`);
    records.push({ uuid, name: `${s.id} ${role}`, layer: "default", pointType: "POINT", attrs: {
      dis: `Weather ${def.name}`, markers: ["point", "his", ...def.markers].join(","), siteRef: s.id,
      weatherStationRef: `wx-${s.id}`, unit: "°F", kind: "Number" } });
    signals.set(uuid, (t) => signal(role, 0, t));
  }
}
// FDD hook result points (what nf-app/hooks/fdd.js writes): hourly fault % per rule.
const FAULTS = [
  ["AHU-1", "ECON-1", (t) => (occ(t) && oat(t) > 70 ? 60 : 0)], ["AHU-1", "DMP-1", () => 0],
  ["AHU-1", "ECON-2", (t) => (occ(t) && oat(t) > 70 ? 100 : 0)], ["AHU-1", "FC1", (t) => (occ(t) ? 35 : 0)],
  ["AHU-1", "OAT-METEO", () => 80], ["AHU-2", "AHU-SATDEV", (t) => (occ(t) ? 90 : 0)],
  ["AHU-2", "SCHED-247", () => 100], ["AHU-2", "AHU-DUCTHI", () => 0], ["AHU-1", "MECH-OAT-1", () => 0],
  ["VAV-3", "ZONE-COMFORT-PCT", (t) => (occ(t) ? 70 : 0)], ["VAV-1", "ZONE-COMFORT-PCT", () => 0],
  ["CH-1", "CHW-1", (t) => (occ(t) && oat(t) > 55 ? 75 : 0)], ["MTR-N", "UTIL-INTERVAL", () => 0],
  ["AHU-1", "SV-FLATLINE", () => 0], ["AHU-1", "SV-RANGE", () => 0], ["AHU-1", "SV-SPIKE", (t) => (day(t) % 3 === 0 && H(t) === 4 ? 10 : 0)],
];
for (const [eq, rule, fn] of FAULTS) {
  const e = equips.find((x) => x.id === eq);
  const uuid = uuidOf(`result/${eq}/${rule}`);
  records.push({ uuid, name: `${eq}/${rule}`, layer: "default", pointType: "POINT", attrs: {
    dis: `${eq} ${rule}`, markers: "point,his,fault,fdd", kind: "Number", unit: "%",
    siteRef: sites[e.site].id, equipRef: eq, ruleRef: rule, fddWindowHours: "24" } });
  signals.set(uuid, (t) => fn(Math.floor(t / 3600e3) * 3600e3));
}
const withLatest = (r) => (signals.has(r.uuid) ? { ...r, latestValue: { ts: new Date(NOW).toISOString(), double: signals.get(r.uuid)(NOW) } } : r);

// ---- API ----------------------------------------------------------------------------------
function textOf(q) { return q && q.field ? [q.field.property, q.field.text] : null; }
function query(body) {
  const layer = body.layer || "default";
  const f = textOf(body.structuredQuery);
  const out = records.filter((r) => (layer === "model" ? r.layer === "model" : true)
    && (!f || String((r.attrs || {})[f[0]] ?? "") === f[1])).map(withLatest);
  return { points: out, totalCount: String(out.length) };
}

const AGG = {
  AVERAGE: (xs) => xs.reduce((a, b) => a + b, 0) / xs.length, MIN: (xs) => Math.min(...xs), MAX: (xs) => Math.max(...xs),
  SUM: (xs) => xs.reduce((a, b) => a + b, 0), FIRST: (xs) => xs[0], LAST: (xs) => xs[xs.length - 1], COUNT: (xs) => xs.length,
};
function data(params) {
  const uuids = params.getAll("uuids");
  const from = Math.max(START, Date.parse(params.get("from") || new Date(START).toISOString()));
  const to = Math.min(NOW, Date.parse(params.get("to") || new Date(NOW).toISOString()));
  const win = (parseInt(params.get("window") || "300", 10) || 300) * 1e3;
  const agg = AGG[params.get("method") || "AVERAGE"] || AGG.AVERAGE;
  return { data: uuids.map((uuid) => {
    const fn = signals.get(uuid);
    const values = [];
    if (fn) for (let b = Math.floor(from / win) * win; b < to; b += win) {
      const xs = [];
      for (let t = Math.max(b, START); t < Math.min(b + win, NOW); t += 300e3) xs.push(fn(t));
      if (xs.length) values.push({ ts: new Date(b).toISOString(), double: Math.round(agg(xs) * 1000) / 1000 });
    }
    return { uuid, values };
  }) };
}

const json = (res, code, body) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json" };
let runs = [];
// In-memory store of what a client WROTE (the synthetic building itself stays read-only).
//   POST /api/v1/point/points  { points: [record] }                   -> writes.points
//   POST /api/v1/point/data    { uuid, values: [..] }                 -> writes.data  (one point)
//   POST /api/v1/points/data   { points: [{ uuid, values: [..] }] }   -> writes.data  (AddData, batched)
//   GET /api/v1/_mock/writes   (mock only, not an NF route) returns the store; DELETE clears it.
// writes.calls lists every accepted write request: { route, n = records or points in it }.
const writes = { points: [], data: [], calls: [] };
const note = (route, n) => writes.calls.push({ route, n });

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const p = url.pathname;
  let body = "";
  for await (const chunk of req) body += chunk;
  let b = {};
  try { b = body ? JSON.parse(body) : {}; } catch (e) { return json(res, 400, { error: "mock-nf: invalid JSON body" }); }
  if (p === "/" || p === "/api/v1/apps/static/open-fdd") { res.writeHead(302, { Location: APP_PREFIX }); return res.end(); }
  if (p === `${APP_PREFIX}version.json`) {
    // Same shape nf_app_sync.py writes on deploy (VERSION + git commit); dev mock marks it "dev".
    const root = path.join(HERE, "..", "..");
    const version = fs.existsSync(path.join(root, "VERSION")) ? fs.readFileSync(path.join(root, "VERSION"), "utf8").trim() : "0.0.0";
    return json(res, 200, { version, commit: "", dirty: true, deployed: "dev mock" });
  }
  if (p.startsWith(APP_PREFIX)) {
    const rel = decodeURIComponent(p.slice(APP_PREFIX.length)) || "index.html";
    const file = path.join(STATIC, rel);
    if (!file.startsWith(STATIC) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
    // Same security headers as the Caddy front door (deploy/nf-caddy/routes.caddy), so the CI ZAP
    // scan of the mock reflects a production deployment.
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream", "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=(), usb=(), payment=()",
      "Content-Security-Policy": "frame-ancestors 'self'" });
    return res.end(fs.readFileSync(file));
  }
  if (p === "/api/v1/platform/info") return json(res, 200, { version: "mock-3.10", provider: "", resources: [{ memory: { totalBytes: String(4 * 1024 ** 3) } }] });
  if (p === "/api/v1/point/query") return json(res, 200, query(b));
  if (p === "/api/v1/point/data" && req.method !== "POST") return json(res, 200, data(url.searchParams));
  if (p === "/api/v1/_mock/writes") {
    if (req.method === "DELETE") { writes.points.length = 0; writes.data.length = 0; writes.calls.length = 0; return json(res, 200, {}); }
    return json(res, 200, writes);
  }
  if (req.method === "POST" && p === "/api/v1/point/points") {
    if (!Array.isArray(b.points)) return json(res, 400, { error: "points must be an array" });
    writes.points.push(...b.points); note(p, b.points.length);
    return json(res, 200, { results: b.points.map((r) => ({ uuid: r.uuid, success: true, newVersion: "1" })) });
  }
  if (req.method === "POST" && p === "/api/v1/point/data") {
    if (!b.uuid || !Array.isArray(b.values)) return json(res, 400, { error: "uuid and values are required" });
    writes.data.push({ uuid: b.uuid, values: b.values }); note(p, 1);
    return json(res, 200, { success: true });
  }
  if (req.method === "POST" && p === "/api/v1/points/data") {
    if (!Array.isArray(b.points) || b.points.some((x) => !x || !x.uuid)) return json(res, 400, { error: "points[].uuid is required" });
    for (const x of b.points) writes.data.push({ uuid: x.uuid, values: x.values || [] });
    note(p, b.points.length);
    return json(res, 200, { success: true });
  }
  if (p === "/api/v1/point/updates/data") { res.writeHead(204); return res.end(); }
  if (p === "/api/v1/sites") return json(res, 200, { sites: sites.map((s) => ({ id: s.id, name: s.dis, latitude: s.lat, longitude: s.lon, timezone: s.tz })) });
  if (p === "/api/v1/bacnet/configuration") return json(res, 200, { deviceInstance: 54321, deviceName: "MockNF" });
  if (p === "/api/v1/bacnet/ports") return json(res, 200, { ports: [] });
  if (p === "/api/v1/bacnet/local") return json(res, 200, { objects: [] });
  if (p === "/api/v1/bacnet/readproperty") {
    const prop = url.searchParams.get("property_id") || "";
    return json(res, 200, { value: { characterString: { PROP_OBJECT_NAME: "MockNF", PROP_VENDOR_NAME: "Normal (mock)", PROP_MODEL_NAME: "mock-nf", PROP_FIRMWARE_REVISION: "3.10-mock" }[prop] || "" } });
  }
  const hook = p.match(/^\/api\/v1\/apps\/([^/]+)\/hooks\/([^/]+)(\/runs)?$/);
  if (hook && !hook[3] && req.method === "POST") { const pid = runs.length + 1; runs.push({ pid, state: "STATE_SUCCESS", results: { "": { events: [{ message: "mock run: nothing executed" }] } } }); return json(res, 200, { pid }); }
  if (hook && hook[3]) return json(res, 200, { runs });
  json(res, 404, { error: `mock-nf: no route for ${req.method} ${p}` });
});
// MOCK_HOST=0.0.0.0 lets a container (e.g. a local ZAP scan) reach the mock; default stays loopback.
const HOST = process.env.MOCK_HOST || "127.0.0.1";
server.listen(PORT, HOST, () => console.log(`mock NF: http://${HOST}:${PORT}${APP_PREFIX}  (${records.length} records, ${DAYS} days)`));
