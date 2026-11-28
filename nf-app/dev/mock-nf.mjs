#!/usr/bin/env node
// Mock Normal Framework for developing / testing the Open-FDD app on any PC (no NF box needed).
//
//   node nf-app/dev/mock-nf.mjs [port]          → http://127.0.0.1:8765/api/v1/apps/static/open-fdd/
//   MOCK_STATIC=lite/static node nf-app/dev/mock-nf.mjs 8766    → the same mock serving the Lite pages
//
// Serves nf-app/static at the NF app URL and answers the NF API calls the app makes
// (point/query, point/data with server-side resampling, schedules (read-only), platform/info, bacnet/*, hook runs)
// from a synthetic two-site building: AHUs, VAVs, a chiller plant + tower, a boiler, electric
// meters, a weather station, and FDD hook result points with some faults. Points are built
// from fdd-catalog.json roles (NF class + Haystack markers), exactly how a real site is tagged,
// so every RCx/FDD view binds. Deterministic: same data every run. Read-only; nothing to break.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import * as real from "./nf-real.mjs";   // real NF 3.10.11 shapes and quirks, recorded in tests/fixtures/nf-real

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = process.env.MOCK_STATIC ? path.resolve(process.env.MOCK_STATIC) : path.join(HERE, "..", "static");   // MOCK_STATIC=lite/static serves the Lite pages
const APP_PREFIX = "/api/v1/apps/static/open-fdd/";
const PORT = Number(process.argv[2]) || 8765;
const catalog = JSON.parse(fs.readFileSync(path.join(HERE, "..", "static", "fdd-catalog.json"), "utf8"));
const DAYS = 8;
// MOCK_PROFILE=real-nf reproduces what real NF 3.10 gives a site with nothing configured (#1584): the model site
// has no tz, /api/v1/sites is empty, platform/info reports the container zone (Etc/UTC). MOCK_APP_TIMEZONE sets the
// open-fdd app option "timezone". Without the profile every site carries tz and /sites returns it.
const REAL_NF = process.env.MOCK_PROFILE === "real-nf";
const APP_TZ_OPTION = process.env.MOCK_APP_TIMEZONE || "";
// MOCK_NOW=2026-11-18T20:00:00Z freezes the history clock (tests use this so a trailing
// 2-day window cannot fall over a weekend; see #1647). Unset = wall clock.
function mockNowMs() {
  const raw = process.env.MOCK_NOW;
  const ms = raw ? Date.parse(raw) : Date.now();
  if (!Number.isFinite(ms)) throw new Error(`MOCK_NOW is not a valid time: ${raw}`);
  return Math.floor(ms / 300e3) * 300e3;
}
const NOW = mockNowMs();
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
    case "outdoor_air_intake_temperature": return oat(t) + 1.5 + n(2);                       // BAS sensor reads a bit warm
    case "weather_service_air_temperature": return Math.round(oat(t) * 10) / 10;
    case "weather_service_air_dew_point_temperature": return oat(t) - 12 + n(3);
    case "weather_service_air_wet_bulb_temperature": return oat(t) - 6 + n(4);
    case "outdoor_air_intake_relative_humidity": return 55 + 20 * wave(t, 24, 3) + n(5) * 4;
    case "return_air_temperature": return 72 + n(6) + (o ? 1 : -2);
    case "discharge_air_temperature": return o ? 55 + (i === 1 ? 4 : 0) + n(7) : 68 + n(7);   // AHU-2 runs warm (SATDEV)
    case "discharge_air_temperature_setpoint": return o ? 55 : 65;
    case "mixed_air_temperature": { const d = signal("outdoor_air_intake_damper_position_command", i, t) / 100; return d * oat(t) + (1 - d) * signal("return_air_temperature", i, t) + n(8); }
    case "outdoor_air_intake_damper_position_command": return o ? (i === 0 && oat(t) > 70 ? 80 : Math.min(100, Math.max(15, (68 - oat(t)) * 4))) : 0;
    case "supply_fan_command": return i === 1 ? 1 : o;                          // AHU-2 runs 24/7 (SCHED-247)
    case "supply_fan_operating_status": return signal("supply_fan_command", i, t);
    case "cooling_valve_position_command": return o && oat(t) > 60 ? Math.min(100, (oat(t) - 60) * 5) : 0;
    case "heating_valve_position_command": return o && oat(t) < 50 ? Math.min(100, (50 - oat(t)) * 5) : 0;
    case "discharge_air_static_pressure": return o || i === 1 ? 1.2 + 0.15 * n(9) - (i === 0 ? 0.35 : 0) : 0.02;
    case "discharge_air_static_pressure_setpoint": return o || i === 1 ? 1.25 : 0;
    case "zone_air_temperature": return 72 + 2.5 * wave(t, 24, i) + (i === 2 ? 4 : 0) - (i === 5 ? 6 : 0) + n(10);   // VAV-3 runs hot, VAV-6 runs cold
    case "zone_air_temperature_setpoint": return o ? 72 : 76;
    case "zone_cooling_air_temperature_setpoint": return o ? 74 : 80;
    case "zone_heating_air_temperature_setpoint": return o ? 70 : 64;
    case "discharge_air_volume_flow_rate": return o ? 450 + 150 * wave(t, 6, i) + 20 * n(11) - (i === 3 ? 300 : 0) : 120;
    case "discharge_air_volume_flow_rate_setpoint": return o ? 450 + 150 * wave(t, 6, i) : 120;
    case "damper_position": case "damper_position_command": return i === 2 ? 100 : i === 6 ? 0 : o ? 40 + 30 * wave(t, 6, i) : 15;  // VAV-3 pinned open, VAV-7 pinned closed
    case "terminal_unit_heating_valve_position_command": return i === 4 ? 100 : o ? 15 + 25 * (1 + wave(t, 5, i)) : 0;   // VAV-5 reheat stuck open
    case "terminal_unit_discharge_air_temperature": return 58 + (signal("terminal_unit_heating_valve_position_command", i, t) / 100) * 30 + n(19);
    case "supply_chilled_water_temperature": return 44 + (o ? 0 : 3) + n(12);
    case "return_chilled_water_temperature": return signal("supply_chilled_water_temperature", i, t) + (o ? 4 : 1.5);    // low ΔT → CHW-1
    case "chiller_operating_status": case "chilled_water_pump_operating_status": case "compressor_operating_status": case "chiller_command": return o && oat(t) > 55 ? 1 : 0;
    case "supply_condenser_water_temperature": return 85 + n(13);
    case "return_condenser_water_temperature": return 94 + n(14);
    case "cooling_tower_fan_command": return o && oat(t) > 60 ? 70 : 0;
    case "supply_hot_water_temperature": return 160 - (oat(t) - 40) * 0.8 + n(15);
    case "return_hot_water_temperature": return signal("supply_hot_water_temperature", i, t) - 20;
    case "pump_operating_status": return o ? 1 : 0;
    case "electric_power": return (i === 0 ? 220 : 140) + 160 * o + 3 * Math.max(0, oat(t) - 65) + 10 * n(16);
    case "electric_energy": return ((t - START) / 3600e3) * ((i === 0 ? 300 : 200)) + 5 * n(17);
    default: return 50 + 10 * wave(t, 24, i) + n(18);
  }
}

const UNITS = (role) => {
  const scale = catalog.roles[role] && catalog.roles[role].scale;
  if (scale === "DEG_C" || scale === "K") return "°F";
  if (scale === "PERCENT_RH") return "%RH";
  if (scale === "PERCENT") return "%";
  if (scale === "PA") return "inH₂O";
  if (scale === "L-PER-SEC") return "cfm";
  if (scale === "KiloW") return "kW";
  if (scale === "KiloW-HR") return "kWh";
  if (scale === "A") return "A";
  if (scale === "PPM") return "ppm";
  return "";
};
const isBool = (role) => catalog.roles[role] && catalog.roles[role].scale === "boolean";

// ---- the building -----------------------------------------------------------------------
const sites = [
  { id: "site-north", dis: "North Campus Hall", area: "52000", tz: "America/Chicago", lat: 43.07, lon: -89.4 },
  { id: "site-south", dis: "South Annex", area: "31000", tz: "America/Chicago", lat: 43.05, lon: -89.42 },
];
const equips = [
  { id: "AHU-1", site: 0, markers: "equip,ahu", roles: ["discharge_air_temperature", "discharge_air_temperature_setpoint", "mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_temperature", "outdoor_air_intake_damper_position_command", "supply_fan_command", "supply_fan_operating_status", "cooling_valve_position_command", "heating_valve_position_command", "discharge_air_static_pressure", "discharge_air_static_pressure_setpoint"] },
  { id: "AHU-2", site: 0, markers: "equip,ahu", roles: ["discharge_air_temperature", "discharge_air_temperature_setpoint", "mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_temperature", "outdoor_air_intake_damper_position_command", "supply_fan_command", "supply_fan_operating_status", "cooling_valve_position_command", "discharge_air_static_pressure", "discharge_air_static_pressure_setpoint"] },
  // VAVs are fed by AHU-1 (odd) / AHU-2 (even) through the Haystack ref airRef, like a real model
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ id: `VAV-${n}`, site: 0, markers: "equip,vav", airRef: n % 2 ? "AHU-1" : "AHU-2",
    roles: ["zone_air_temperature", "zone_air_temperature_setpoint", "zone_cooling_air_temperature_setpoint", "zone_heating_air_temperature_setpoint", "discharge_air_volume_flow_rate", "discharge_air_volume_flow_rate_setpoint", "damper_position", "terminal_unit_heating_valve_position_command", "terminal_unit_discharge_air_temperature"] })),
  { id: "CH-1", site: 0, markers: "equip,chiller", roles: ["supply_chilled_water_temperature", "return_chilled_water_temperature", "chiller_operating_status", "chiller_command", "chilled_water_pump_operating_status", "supply_condenser_water_temperature", "return_condenser_water_temperature", "compressor_operating_status"] },
  { id: "CT-1", site: 0, markers: "equip,coolingTower", roles: ["supply_condenser_water_temperature", "return_condenser_water_temperature", "cooling_tower_fan_command"] },
  { id: "BLR-1", site: 0, markers: "equip,boiler", roles: ["supply_hot_water_temperature", "return_hot_water_temperature", "pump_operating_status"] },
  { id: "MTR-N", site: 0, markers: "equip,meter,elecMeter", roles: ["electric_power", "electric_energy"] },
  { id: "RTU-S1", site: 1, markers: "equip,ahu,rtu", roles: ["discharge_air_temperature", "discharge_air_temperature_setpoint", "mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_temperature", "outdoor_air_intake_damper_position_command", "supply_fan_command", "supply_fan_operating_status", "discharge_air_static_pressure"] },
  { id: "MTR-S", site: 1, markers: "equip,meter,elecMeter", roles: ["electric_power", "electric_energy"] },
];
const uuidOf = (name) => {
  const h = crypto.createHash("sha1").update(`mock:${name}`).digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-5${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
};

const records = [];   // model-layer entities + default-layer points
const signals = new Map();   // uuid -> (t) => value
for (const s of sites) {
  records.push({ uuid: uuidOf(s.id), name: s.id, layer: "model", pointType: "SITE",
    attrs: { id: s.id, dis: s.dis, markers: "site", area: s.area, ...(REAL_NF ? {} : { tz: s.tz }) } });
}
equips.forEach((e, ei) => {
  const site = sites[e.site].id;
  records.push({ uuid: uuidOf(e.id), name: e.id, layer: "model", pointType: "EQUIPMENT",
    attrs: { id: e.id, dis: e.id, markers: e.markers, siteRef: site, ...(e.airRef ? { airRef: e.airRef } : {}) } });
  const idx = equips.filter((x) => x.markers === e.markers).indexOf(e);
  for (const role of e.roles) {
    const def = catalog.roles[role];
    const uuid = uuidOf(`${e.id}/${role}`);
    records.push({ uuid, name: `${e.id} ${role}`, layer: "default", pointType: "POINT", attrs: {
      dis: `${e.id} ${def.name}`, markers: ["point", "his", ...def.markers].join(","), class: def.classes[0] || "",
      equipRef: e.id, siteRef: site,
      unit: e.id === "CT-1" && role === "supply_condenser_water_temperature" ? "" : UNITS(role),
      kind: isBool(role) ? "Bool" : "Number" } });
    signals.set(uuid, (t) => signal(role, idx, t));
  }
});
for (const s of sites) {
  for (const role of ["weather_service_air_temperature", "weather_service_air_dew_point_temperature", "weather_service_air_wet_bulb_temperature"]) {
    const def = catalog.roles[role];
    const uuid = uuidOf(`${s.id}/${role}`);
    records.push({ uuid, name: `${s.id} ${role}`, layer: "default", pointType: "POINT", attrs: {
      dis: `Weather ${def.name}`, markers: ["point", "his", ...def.markers].join(","), siteRef: s.id,
      weatherStationRef: `wx-${s.id}`, unit: "°F", kind: "Number" } });
    signals.set(uuid, (t) => signal(role, 0, t));
  }
}
// Site occupancy: an occupancy point on site-north and the NF schedule that targets it (read-only
// GET /api/v1/schedules in the NF ScheduleManager shape: camelCase Schedule, weeklySchedule.days[0] = Monday,
// timeValues steps, specialEvents with a date). site-south has no schedule, so it uses the 4.x default calendar.
const occUuid = uuidOf("site-north/occ");
records.push({ uuid: occUuid, name: "site-north occupancy", layer: "default", pointType: "POINT", attrs: {
  dis: "North occupancy", markers: "point,his,occ,cmd", class: "occupied-cmd", siteRef: sites[0].id, unit: "", kind: "Bool" } });
signals.set(occUuid, (t) => occ(t));
const holiday = new Date(NOW - 3 * 86400e3);
const weekdayDay = { timeValues: [{ time: { hour: 7 }, value: { boolean: true } }, { time: { hour: 18 }, value: { boolean: false } }] };
const schedules = [{
  uuid: uuidOf("schedule/site-north"), name: "North occupancy", layer: "local", outOfService: false, defaultValue: { boolean: false },
  weeklySchedule: { days: [weekdayDay, weekdayDay, weekdayDay, weekdayDay, weekdayDay, {}, {}] },
  specialEvents: [{ name: "Mock holiday", date: { year: holiday.getUTCFullYear(), month: holiday.getUTCMonth() + 1, day: holiday.getUTCDate() },
    priority: 1, timeValues: [{ time: {}, value: { boolean: false } }] }],
  targets: [{ pointUuid: occUuid, layer: "default" }],
}];
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
const pointKey = (record) => JSON.stringify([record.layer || "default", record.uuid]);
const seedPoints = new Map(records.map((record) => [pointKey(record), record]));
const updatedPoints = new Map();

// ---- API ----------------------------------------------------------------------------------
function textOf(q) { return q && q.field ? [q.field.property, q.field.text] : null; }
function query(body) {
  const layer = body.layer || "default";
  const f = textOf(body.structuredQuery);
  const out = [...new Map([...seedPoints, ...updatedPoints]).values()].filter((r) => (layer === "default" || r.layer === layer)
    && (!f || String((r.attrs || {})[f[0]] ?? "") === f[1])).map(withLatest)
    .sort((a, b) => a.uuid.localeCompare(b.uuid));
  // Like NF 3.10.x: pages by pageOffset + pageSize and reports totalCount; nextPageToken is always "" (#1550).
  // NF 3.10.9-1 returns no rows for an absent/zero pageSize and ignores tokens. NF takes the proto field names in
  // camelCase or snake_case (page_size / page_offset), and ignores fields it does not know.
  const size = Number(body.pageSize ?? body.page_size) || 0;
  const offRaw = Number(body.pageOffset ?? body.page_offset);
  const off = offRaw > 0 ? offRaw : 0;
  return { points: out.slice(off, off + size).map((r) => real.realPoint(r, layer)), totalCount: String(out.length), nextPageToken: "" };
}

const AGG = {
  AVERAGE: (xs) => xs.reduce((a, b) => a + b, 0) / xs.length, MIN: (xs) => Math.min(...xs), MAX: (xs) => Math.max(...xs),
  SUM: (xs) => xs.reduce((a, b) => a + b, 0), FIRST: (xs) => xs[0], LAST: (xs) => xs[xs.length - 1], COUNT: (xs) => xs.length,
};
// NF answers a malformed GET /point/data with an empty 400: text/plain for a bad window, method or time, application/grpc for a bad uuid.
function dataProblem(params) {
  if (params.getAll("uuids").some((u) => !real.UUID_RE.test(u))) return "application/grpc";
  if (params.has("window") && real.parseWindow(params.get("window")) === null) return "text/plain";
  if (params.has("window") && params.has("method") && !real.AGG_METHODS.has(params.get("method"))) return "text/plain";
  for (const k of ["from", "to"]) if (params.has(k) && !Number.isFinite(Date.parse(params.get(k)))) return "text/plain";
  return "";
}
function data(params) {
  const uuids = params.getAll("uuids");
  const from = Math.max(START, Date.parse(params.get("from") || new Date(START).toISOString()));
  const to = Math.min(NOW, Date.parse(params.get("to") || new Date(NOW).toISOString()));
  const win = (params.has("window") ? real.parseWindow(params.get("window")) : 0) * 1e3;
  const count = Math.min(10000, Math.max(1, parseInt(params.get("count") || "10000", 10) || 10000));
  const reverse = params.get("reverse") === "true";
  const agg = AGG[params.get("method") || "AVERAGE"] || AGG.AVERAGE;
  return { data: uuids.map((uuid) => {
    const fn = signals.get(uuid);
    const buckets = new Map();
    // NF's time bounds select the raw samples before resampling. With no window,
    // each sample keeps its own timestamp and count applies per UUID.
    if (fn) for (let t = Math.ceil(from / 300e3) * 300e3; t <= to; t += 300e3) {
      const bucket = win ? Math.floor(t / win) * win : t;
      if (!buckets.has(bucket)) buckets.set(bucket, []);
      buckets.get(bucket).push(fn(t));
    }
    const ordered = [...buckets];
    if (reverse) ordered.reverse();
    return { uuid, values: ordered.slice(0, count).map(([t, xs]) => ({
      ts: win ? real.bucketTs(t) : real.rawTs(t), double: Math.round((win ? agg(xs) : xs[0]) * 1000) / 1000,
    })) };
  }) };
}

const json = (res, code, body) => {
  res.writeHead(code, { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff" });
  res.end(JSON.stringify(body));
};
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json" };
// Hook runs per "app/hook", newest first, in NF's shape (nf-real.mjs makeRun). pid counts up per hook.
const hookRuns = new Map();
const hookIds = real.manifestHookIds(path.join(HERE, "..", ".."));
// In-memory store of what a client WROTE (the synthetic building itself stays read-only).
//   POST /api/v1/point/points  { points: [record] }                   -> writes.points
//   POST /api/v1/point/data    { uuid, values: [..] }                 -> writes.data  (one point)
//   POST /api/v1/points/data   { points: [{ uuid, values: [..] }] }   -> writes.data  (AddData, batched)
//   GET /api/v1/_mock/writes   (mock only, not an NF route) returns the store; DELETE clears it.
// writes.calls lists every accepted write request: { route, n = records or points in it }.
const writes = { points: [], data: [], calls: [] };
const note = (route, n) => writes.calls.push({ route, n });

// Minimal installer API fixture. It is isolated from the synthetic point store and exists only
// to exercise snapshot/verify/rollback behavior; it does not model authentication or NF secrets.
const installApp = { id: "open-fdd", name: "Open-FDD", status: "STATUS_INSTALLED", files: [],
  options: [], configuration: {}, hooks: [] };
const installFiles = new Map();
let failVersionRead = false;
let failVersionReadOnNextWrite = false;

// Let the fixture's front-door guard respond before Node rejects a large request line.
const server = http.createServer({ maxHeaderSize: 64 * 1024 }, async (req, res) => {
  // Model the request-line + header ceiling seen behind common NF front doors.
  const headerBytes = req.rawHeaders.reduce((n, part) => n + Buffer.byteLength(part), 0);
  if (req.method === "GET" && (Buffer.byteLength(req.url || "") > 6500 || headerBytes > 8192)) {
    return json(res, 431, { error: "request URL or headers exceed the mock NF limit" });
  }
  const url = new URL(req.url, `http://${req.headers.host}`);
  const p = url.pathname;
  let body = "";
  for await (const chunk of req) body += chunk;
  let b = {};
  try { b = body ? JSON.parse(body) : {}; } catch (e) { return real.textError(res, 400); }   // NF: an empty 400 text/plain
  if (p === "/api/v1/_mock/install/state" && req.method === "POST") {
    installApp.files = Array.isArray(b.files) ? b.files.map((path) => ({ path })) : [];
    installApp.options = b.options || [];
    installApp.configuration = b.configuration || {};
    installApp.hooks = b.hooks || [];
    installFiles.clear();
    for (const [name, value] of Object.entries(b.contents || {})) installFiles.set(name, Buffer.from(value, "base64"));
    failVersionRead = false;
    failVersionReadOnNextWrite = b.failVersionRead === true;
    return json(res, 200, { success: true });
  }
  if (p === "/api/v1/apps") {
    const options = [...(installApp.options || []).filter((o) => o.name !== "timezone"), ...(APP_TZ_OPTION ? [{ name: "timezone", value: { string: APP_TZ_OPTION } }] : [])];
    // The real list entry has every one of these fields; files carry mtime / hash / size (size is an int64 string).
    const files = installApp.files.map((f) => ({ path: f.path, mtime: new Date(NOW).toISOString(), hash: "",
      size: String((installFiles.get(f.path) || Buffer.alloc(0)).length) }));
    const app = { id: installApp.id, name: installApp.name, description: "", runtime: "RUNTIME_NODE_JS", compatibilityDate: "",
      hooks: installApp.hooks, files, gitUrl: "", status: installApp.status, options, minNfVersion: "", statusMessage: "",
      configuration: installApp.configuration,   // mock-only: the installer tests read back what they PATCHed (real NF lists no such field)
      auth: { apiKey: { scopes: ["normalgw.hpl.v1.readwrite"], clientId: "<redacted>", clientSecret: "<redacted>" } } };
    return json(res, 200, { applications: [app], totalCount: "1" });
  }
  const oneApp = p.match(/^\/api\/v1\/apps\/([^/]+)$/);
  if (oneApp && req.method === "GET") {         // an app that is not installed is an EMPTY list, not a 404
    if (oneApp[1] !== installApp.id) return json(res, 200, { applications: [], totalCount: "0" });
    const options = installApp.options || [];
    return json(res, 200, { applications: [{ id: installApp.id, name: installApp.name, status: installApp.status, hooks: installApp.hooks, options }], totalCount: "1" });
  }
  const appFile = p.match(/^\/api\/v1\/apps\/open-fdd\/files(\/.*)$/);
  if (appFile && req.method === "DELETE") {
    installFiles.delete(appFile[1]);
    installApp.files = installApp.files.filter((x) => x.path !== appFile[1]);
    return json(res, 200, { success: true });
  }
  if (appFile && req.method === "GET") {
    if (appFile[1] === "/static/version.json" && failVersionRead) return json(res, 503, { error: "forced verify failure" });
    const data = installFiles.get(appFile[1]);
    return data ? json(res, 200, { data: data.toString("base64") }) : json(res, 404, { error: "missing file" });
  }
  if (appFile && req.method === "POST") {
    if (typeof b !== "string") return json(res, 400, { error: "file body must be base64 string" });
    const data = Buffer.from(b, "base64");
    installFiles.set(appFile[1], data);
    if (appFile[1] === "/static/version.json") {
      failVersionRead = failVersionReadOnNextWrite;
      failVersionReadOnNextWrite = false;
    }
    if (!installApp.files.some((x) => x.path === appFile[1])) installApp.files.push({ path: appFile[1] });
    return json(res, 200, { success: true });
  }
  if (p === "/api/v1/apps/open-fdd" && req.method === "PATCH") {
    for (const field of b.updateMask || []) if (field in b) installApp[field] = b[field];
    return json(res, 200, { success: true });
  }
  if (p === "/api/v1/apps/open-fdd/hooks" && req.method === "POST") {
    const i = installApp.hooks.findIndex((h) => h.id === b.id);
    if (i < 0) installApp.hooks.push(b); else installApp.hooks[i] = b;
    return json(res, 200, { success: true });
  }
  const appHook = p.match(/^\/api\/v1\/apps\/open-fdd\/hooks\/([^/]+)$/);
  if (appHook && req.method === "DELETE") {
    const id = decodeURIComponent(appHook[1]);
    installApp.hooks = installApp.hooks.filter((h) => h.id !== id);
    return json(res, 200, { success: true });
  }
  if (p === "/api/v1/apps/open-fdd/dependencies" && req.method === "PATCH") return json(res, 200, { success: true });
  if (p === "/api/v1/apps/open-fdd/restart" && req.method === "PATCH") return json(res, 200, { success: true });
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
  if (p === "/api/v1/platform/info") return json(res, 200, real.platformInfo({ real: REAL_NF, version: "mock-3.10", timezone: REAL_NF ? "Etc/UTC" : "" }));
  if (p === "/api/v1/point/query") {
    // NF: an empty application/grpc 400 for a negative paging argument or a layer it does not have.
    if (Number(b.pageOffset ?? b.page_offset) < 0 || Number(b.pageSize ?? b.page_size) < 0) return real.grpcError(res, 400);
    if (b.layer && !real.LAYER_NAMES.has(b.layer)) return real.grpcError(res, 400);
    return json(res, 200, query(b));
  }
  if (p === "/api/v1/point/data" && req.method !== "POST") {
    const bad = dataProblem(url.searchParams);
    return bad ? real.emptyError(res, 400, bad) : json(res, 200, data(url.searchParams));
  }
  if (p === "/api/v1/_mock/writes") {
    if (req.method === "DELETE") {
      writes.points.length = 0;
      writes.data.length = 0;
      writes.calls.length = 0;
      updatedPoints.clear();
      return json(res, 200, {});
    }
    return json(res, 200, writes);
  }
  if (req.method === "POST" && p === "/api/v1/point/points") {
    if (!Array.isArray(b.points) || b.points.some((point) => !point || typeof point.uuid !== "string" || !point.uuid)) {
      return json(res, 400, { error: "points must be an array of records with UUIDs" });
    }
    for (const point of b.points) {
      // Real NF accepts a record with no layer, or with "default" or an unknown layer name, answers success:true
      // and applies NOTHING (only an explicit base layer such as "model" or "automation" is written). Tags posted
      // without layer:"model" are silently lost.
      if (!real.BASE_LAYERS.has(point.layer)) continue;
      const key = pointKey(point);
      const prior = updatedPoints.get(key) || seedPoints.get(key);
      const attrs = Object.fromEntries(Object.entries(point.attrs ?? {}).map(([k, v]) => [k, v ?? ""]));
      updatedPoints.set(key, { ...prior, ...point, attrs: { ...prior?.attrs, ...attrs } });
    }
    writes.points.push(...b.points); note(p, b.points.length);
    return json(res, 200, { results: b.points.map((r, i) => real.updateResult(r, writes.points.length - b.points.length + i)) });
  }
  if (req.method === "POST" && p === "/api/v1/point/data") {
    if (!b.uuid || !Array.isArray(b.values)) return json(res, 400, { error: "uuid and values are required" });
    writes.data.push({ uuid: b.uuid, values: b.values }); note(p, 1);
    return json(res, 200, { success: true });
  }
  if (req.method === "POST" && p === "/api/v1/points/data") {
    if (!Array.isArray(b.points) || b.points.some((x) => !x || !real.UUID_RE.test(String(x.uuid || "")))) return real.grpcError(res, 400);   // NF: empty 400 grpc for a missing or malformed uuid
    for (const x of b.points) writes.data.push({ uuid: x.uuid, values: x.values || [] });
    note(p, b.points.length);
    return json(res, 200, { success: true, taskUuid: "" });
  }
  if (req.method === "GET" && p === "/api/v1/schedules") {   // ScheduleManager.GetSchedules (read-only)
    const off = parseInt(url.searchParams.get("pageOffset") || "0", 10) || 0, size = parseInt(url.searchParams.get("pageSize") || "100", 10) || 100;
    return json(res, 200, { schedules: schedules.slice(off, off + size), totalCount: String(schedules.length) });
  }
  const sched = p.match(/^\/api\/v1\/schedules\/([^/]+)$/);
  if (req.method === "GET" && sched) {                         // ScheduleManager.GetScheduleById
    const one = schedules.find((x) => x.uuid === decodeURIComponent(sched[1]));
    return one ? json(res, 200, { schedule: one }) : real.grpcError(res, 404);   // NF: an empty application/grpc 404
  }
  if (p === "/api/v1/equipment/classes") return json(res, 200, real.recorded("equipment__classes"));   // empty list without a page size, total as a string
  if (p === "/api/v1/point/updates/data") { res.writeHead(204); return res.end(); }
  // Real NF 3.10: GET /sites lists none until a site is configured, yet its totalCount still counts the model SITE records.
  if (p === "/api/v1/sites") return json(res, 200, REAL_NF ? { sites: [], totalCount: String(sites.length) } : { sites: sites.map((s) => ({ id: s.id, name: s.dis, latitude: s.lat, longitude: s.lon, timezone: s.tz })) });
  if (p === "/api/v1/bacnet/configuration") return json(res, 200, REAL_NF ? real.recorded("bacnet__configuration") : { ...real.recorded("bacnet__configuration"), deviceInstance: 54321, deviceName: "MockNF" });
  if (p === "/api/v1/bacnet/ports") return json(res, 200, REAL_NF ? real.recorded("bacnet__ports") : { ports: [] });
  if (p === "/api/v1/bacnet/local") return json(res, 200, REAL_NF ? real.recorded("bacnet__local_objects") : { objects: [] });
  if (p === "/api/v1/bacnet/readproperty") {
    // Real NF: property/object names are enum names (a bad name is an empty 400 text/plain); the reply echoes the property
    // and the value carries "array":[]; BACnet-level failures are IN-BAND, a 200 with {error:{errorClass, errorCode}}.
    const q = url.searchParams, prop = q.get("property_id") || "", type = q.get("object_id.object_type") || "";
    // NF checks the names against the BACnet enums; the mock knows only the common ones (a mock-only approximation).
    const KNOWN_PROPS = ["PROP_OBJECT_NAME", "PROP_OBJECT_TYPE", "PROP_OBJECT_IDENTIFIER", "PROP_VENDOR_NAME", "PROP_MODEL_NAME", "PROP_FIRMWARE_REVISION", "PROP_DESCRIPTION", "PROP_PRESENT_VALUE", "PROP_PRIORITY_ARRAY", "PROP_RELINQUISH_DEFAULT", "PROP_UNITS", "PROP_STATUS_FLAGS", "PROP_OUT_OF_SERVICE", "PROP_OBJECT_LIST"];
    if (!KNOWN_PROPS.includes(prop) || !/^OBJECT_[A-Z0-9_]+$/.test(type)) return real.textError(res, 400);
    const property = { objectId: { objectType: type, instance: Number(q.get("object_id.instance") || 0) }, propertyId: prop, arrayIndex: Number(q.get("array_index") || 4294967295) };
    const deviceProps = { PROP_OBJECT_NAME: "MockNF", PROP_VENDOR_NAME: "Normal (mock)", PROP_MODEL_NAME: "mock-nf", PROP_FIRMWARE_REVISION: "3.10-mock" };
    if (type === "OBJECT_DEVICE" && prop in deviceProps) return json(res, 200, { property, value: { characterString: deviceProps[prop], array: [] } });
    if (prop === "PROP_PRESENT_VALUE") return json(res, 200, { property, value: { real: 0, array: [] } });
    return json(res, 200, { error: { errorClass: "ERROR_CLASS_PROPERTY", errorCode: "ERROR_CODE_UNKNOWN_PROPERTY" } });
  }
  const hook = p.match(/^\/api\/v1\/apps\/([^/]+)\/hooks\/([^/]+)(\/runs)?$/);
  if (hook) {
    const id = decodeURIComponent(hook[2]), key = `${hook[1]}/${id}`;
    if (!hookIds.has(id) && !installApp.hooks.some((h) => h.id === id)) return real.grpcError(res, 404);   // unknown hook: empty 404
    const list = hookRuns.get(key) || [];
    if (!hook[3] && req.method === "POST") {
      const run = real.makeRun(list.length + 1, b, ["mock run: nothing executed"]);
      hookRuns.set(key, [run, ...list]);
      return json(res, 200, { pid: run.pid, groups: [""] });
    }
    if (hook[3] && req.method === "GET") {
      // page_size runs, newest first; "results" stays {} unless include_results=true (events are in results).
      const size = Number(url.searchParams.get("page_size")) || 10;
      const withResults = url.searchParams.get("include_results") === "true";
      return json(res, 200, { runs: list.slice(0, size).map((r) => (withResults ? r : { ...r, results: {} })), totalCount: String(list.length) });
    }
  }
  // Anything else is not an NF route (see nf-real.mjs unknownRoute): the web console for a GET, 405 otherwise.
  real.unknownRoute(res, req.method);
});
// MOCK_HOST=0.0.0.0 lets a container (e.g. a local ZAP scan) reach the mock; default stays loopback.
const HOST = process.env.MOCK_HOST || "127.0.0.1";
server.listen(PORT, HOST, () => console.log(`mock NF: http://${HOST}:${PORT}${APP_PREFIX}  (${records.length} records, ${DAYS} days)`));
