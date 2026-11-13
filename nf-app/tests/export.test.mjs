// CSV export (static/export.js): escaping, BOM, chunking, column names, unit conversion, fetch loop.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const X = require("../static/export.js");

test("csvCell quotes commas, quotes and line breaks; leaves plain text and numbers alone", () => {
  assert.equal(X.csvCell("plain"), "plain");
  assert.equal(X.csvCell("a,b"), '"a,b"');
  assert.equal(X.csvCell('say "hi"'), '"say ""hi"""');
  assert.equal(X.csvCell("two\nlines"), '"two\nlines"');
  assert.equal(X.csvCell("cr\rhere"), '"cr\rhere"');
  assert.equal(X.csvCell(null), "");
  assert.equal(X.csvCell(undefined), "");
  assert.equal(X.csvCell(NaN), "");
  assert.equal(X.csvCell(-3.5), "-3.5");
  assert.equal(X.csvCell("72 °F / ₂"), "72 °F / ₂");
});

test("buildCsv starts with a UTF-8 BOM, uses CRLF and ends with a line break", () => {
  const csv = X.buildCsv(["timestamp", 'x, "y" [°F]'], [["t1", 1.5], ["t2", null]]);
  assert.equal(csv.charCodeAt(0), 0xfeff);
  assert.equal(csv.slice(1), 'timestamp,"x, ""y"" [°F]"\r\nt1,1.5\r\nt2,\r\n');
  const bytes = Buffer.from(csv, "utf8");
  assert.deepEqual([...bytes.subarray(0, 3)], [0xef, 0xbb, 0xbf]);
  assert.ok(bytes.includes(Buffer.from("°F")));
});

test("chunkRange: consecutive pieces of at most 7 days that cover the range exactly", () => {
  const DAY = 86400e3;
  const t0 = Date.UTC(2026, 10, 1);
  assert.deepEqual(X.chunkRange(t0, t0 + DAY), [{ from: t0, to: t0 + DAY }]);
  const c = X.chunkRange(t0, t0 + 16 * DAY);
  assert.equal(c.length, 3);
  assert.equal(c[0].from, t0);
  assert.equal(c.at(-1).to, t0 + 16 * DAY);
  for (let i = 0; i < c.length; i++) {
    assert.ok(c[i].to - c[i].from <= 7 * DAY);
    if (i) assert.equal(c[i].from, c[i - 1].to);
  }
  assert.equal(c[1].to - c[1].from, 7 * DAY);
  assert.equal(X.chunkRange(t0, t0).length, 0);
  assert.equal(X.chunkRange(t0, t0 + 7 * DAY).length, 1);
});

test("columnName: equip, point and unit in brackets; empty parts dropped", () => {
  assert.equal(X.columnName("AHU-1", "Discharge Air Temp", "°F"), "AHU-1 Discharge Air Temp [°F]");
  assert.equal(X.columnName("", "Outdoor Air Temp", "°C"), "Outdoor Air Temp [°C]");
  assert.equal(X.columnName("AHU-1", "Fan Cmd", ""), "AHU-1 Fan Cmd");
  assert.deepEqual(X.uniqueHeaders(["a", "b", "a", "a"]), ["a", "b", "a (2)", "a (3)"]);
});

test("timestamps: local ISO without Z, UTC ISO, file name stamp", () => {
  const ms = new Date(2026, 10, 5, 13, 5, 9).getTime();            // local wall clock
  assert.equal(X.localIso(ms), "2026-11-05T13:05:09");
  assert.equal(X.utcIso(Date.UTC(2026, 10, 5, 19, 5, 9)), "2026-11-05T19:05:09.000Z");
  assert.equal(X.inputValue(ms), "2026-11-05T13:05");
  const end = new Date(2026, 10, 6, 8, 0, 0).getTime();
  assert.equal(X.fileName("Ben's Bench", ms, end), "open-fdd_Ben_s_Bench_20261105-1305_20261106-0800.csv");
  assert.equal(X.parseNfTs("2026-11-05T19:05:09.123456789Z"), Date.UTC(2026, 10, 5, 19, 5, 9, 123));
});

test("methodFor: MAX for bool and fault/fdd result points, AVERAGE otherwise", () => {
  assert.equal(X.methodFor({ kind: "Number", tags: ["temp", "sensor"] }), "AVERAGE");
  assert.equal(X.methodFor({ kind: "Bool", tags: ["fan", "cmd"] }), "MAX");
  assert.equal(X.methodFor({ kind: "Number", tags: ["fdd", "fault"] }), "MAX");
});

test("resolutions map to NF windows", () => {
  assert.equal(X.windowFor("raw"), 300);
  assert.equal(X.windowFor("5m"), 300);
  assert.equal(X.windowFor("15m"), 900);
  assert.equal(X.windowFor("1h"), 3600);
  assert.equal(X.windowFor("1d"), 86400);
});

test("validate: cap near 200k cells, bad ranges, empty selection", () => {
  const t0 = Date.UTC(2026, 10, 1);
  const DAY = 86400e3;
  assert.match(X.validate({ nPoints: 0, startMs: t0, endMs: t0 + DAY, windowSec: 300 }), /at least one/);
  assert.match(X.validate({ nPoints: 3, startMs: t0 + DAY, endMs: t0, windowSec: 300 }), /after the start/);
  assert.match(X.validate({ nPoints: 3, startMs: NaN, endMs: t0, windowSec: 300 }), /Pick a start/);
  assert.equal(X.validate({ nPoints: 100, startMs: t0, endMs: t0 + DAY, windowSec: 300 }), "");       // 28,800 cells
  const big = X.validate({ nPoints: 100, startMs: t0, endMs: t0 + 30 * DAY, windowSec: 300 });       // 864,000 cells
  assert.match(big, /864,000|864\.000|864 000/);
  assert.match(big, /limit/);
  assert.deepEqual(X.estimateCells(10, t0, t0 + DAY, 3600), { rows: 24, cells: 240 });
});

test("unitFor: display converts per system, stored keeps NF's unit", () => {
  const f2c = X.unitFor("°F", "display", "si");
  assert.equal(f2c.unit, "°C");
  assert.equal(f2c.convert(212), 100);
  assert.equal(f2c.convert(71.6), 22);                       // no float noise
  const f2f = X.unitFor("°F", "display", "imperial");
  assert.equal(f2f.unit, "°F");
  assert.equal(f2f.convert(71.6), 71.6);
  const c2f = X.unitFor("°C", "display", "imperial");
  assert.equal(c2f.unit, "°F");
  assert.equal(c2f.convert(22), 71.6);
  const stored = X.unitFor("°F", "stored", "si");
  assert.equal(stored.unit, "°F");
  assert.equal(stored.convert(71.6), 71.6);
  const pa = X.unitFor("inH2O", "display", "si");
  assert.equal(pa.unit, "Pa");
  assert.ok(Math.abs(pa.convert(1) - 249.0889) < 1e-6);
  assert.equal(X.unitFor("", "display", "si").unit, "");     // unknown/empty unit passes through
  assert.equal(X.unitFor("zz", "display", "si").convert(5), 5);
});

const t = (h, m = 0) => Date.UTC(2026, 10, 5, h, m);
const cols = [
  { uuid: "u1", equip: "AHU-1", dis: "Discharge, Temp", unit: "°F" },
  { uuid: "u2", equip: "AHU-1", dis: 'Fan "Cmd"', unit: "" },
];

test("toCsv: timestamp columns, quoted headers, union of timestamps, unit conversion", () => {
  const data = new Map([
    ["u1", new Map([[t(12), 71.6], [t(12, 15), 75.2]])],
    ["u2", new Map([[t(12, 15), 1], [t(12, 30), 0]])],
  ]);
  const { csv, rows } = X.toCsv({ columns: cols, data, mode: "display", system: "si" });
  assert.equal(rows, 3);
  const lines = csv.slice(1).split("\r\n");
  assert.equal(lines[0], 'timestamp,timestamp_utc,"AHU-1 Discharge, Temp [°C]","AHU-1 Fan ""Cmd"""');
  assert.equal(lines[1], `${X.localIso(t(12))},2026-11-05T12:00:00.000Z,22,`);
  assert.equal(lines[2], `${X.localIso(t(12, 15))},2026-11-05T12:15:00.000Z,24,1`);
  assert.equal(lines[3], `${X.localIso(t(12, 30))},2026-11-05T12:30:00.000Z,,0`);
  assert.equal(lines[4], "");

  const imp = X.toCsv({ columns: cols, data, mode: "display", system: "imperial" }).csv;
  assert.match(imp, /\[°F\]/);
  assert.match(imp, /,71\.6,/);
  const stored = X.toCsv({ columns: cols, data, mode: "stored", system: "si" }).csv;
  assert.match(stored, /\[°F\]/);
  assert.match(stored, /,71\.6,/);
});

test("toCsv: rows outside [start, end) are dropped", () => {
  const data = new Map([["u1", new Map([[t(11), 1], [t(12), 2], [t(13), 3]])]]);
  const { rows } = X.toCsv({ columns: [cols[0]], data, mode: "stored", startMs: t(12), endMs: t(13) });
  assert.equal(rows, 1);
});

test("collect: chunks long ranges, groups by method, merges samples", async () => {
  const DAY = 86400e3;
  const start = Date.UTC(2026, 10, 1);
  const end = start + 15 * DAY;
  const points = [
    { uuid: "a", kind: "Number", tags: ["sensor"] },
    { uuid: "b", kind: "Bool", tags: ["cmd"] },
  ];
  const calls = [];
  const apiFn = async (url) => {
    calls.push(url);
    const q = new URL(url, "http://x").searchParams;
    const from = Date.parse(q.get("from"));
    const data = q.getAll("uuids").map((uuid) => ({
      uuid, values: [{ ts: new Date(from).toISOString().replace("Z", "123Z"), double: q.get("method") === "MAX" ? 1 : 2.5 }],
    }));
    return { data };
  };
  const progress = [];
  const out = await X.collect({ points, startMs: start, endMs: end, windowSec: 900, apiFn, onProgress: (i, n) => progress.push([i, n]) });
  assert.equal(calls.length, 6);                                          // 3 chunks x 2 methods
  for (const u of calls) {
    const q = new URL(u, "http://x").searchParams;
    assert.ok(Date.parse(q.get("to")) - Date.parse(q.get("from")) <= 7 * DAY);
    assert.equal(q.get("window"), "900s");
  }
  assert.ok(calls.some((u) => u.includes("method=MAX") && u.includes("uuids=b") && !u.includes("uuids=a")));
  assert.ok(calls.some((u) => u.includes("method=AVERAGE") && u.includes("uuids=a")));
  assert.equal(out.get("a").size, 3);
  assert.equal(out.get("b").get(start), 1);
  assert.deepEqual(progress.at(-1), [6, 6]);
});

test("collect: batches many points and can be cancelled", async () => {
  const points = Array.from({ length: 95 }, (_, i) => ({ uuid: `p${i}`, kind: "Number", tags: [] }));
  let n = 0;
  await X.collect({ points, startMs: 0, endMs: 3600e3, windowSec: 300, apiFn: async () => { n++; return { data: [] }; } });
  assert.equal(n, 3);                                                     // 40 + 40 + 15
  await assert.rejects(X.collect({ points, startMs: 0, endMs: 3600e3, windowSec: 300, apiFn: async () => ({ data: [] }), isCancelled: () => true }), /cancelled/);
});

test("collect exports 161 and 709 points through request-safe UUID batches", async () => {
  for (const count of [161, 709]) {
    const calls = [];
    const points = Array.from({ length: count }, (_, i) => ({ uuid: `export-${count}-${i}`, units: "", kind: "Number" }));
    const out = await X.collect({ points, startMs: 0, endMs: 3600e3, windowSec: 3600,
      apiFn: async (url) => {
        calls.push(url);
        const ids = new URL(url, "http://mock").searchParams.getAll("uuids");
        return { data: ids.map((uuid) => ({ uuid, values: [{ ts: "2026-01-01T00:00:00Z", double: 2 }] })) };
      } });
    assert.ok(calls.length > 1);
    assert.ok(calls.every((url) => Buffer.byteLength(url) < 8192));
    assert.ok(calls.every((url) => new URL(url, "http://mock").searchParams.getAll("uuids").length <= 40));
    assert.equal(out.size, count);
    assert.ok(points.every((p) => out.get(p.uuid)?.size === 1));
  }
});

// ---- CSV formula injection ----------------------------------------------------------------
test("csvCell neutralises formula-looking text with a leading apostrophe", () => {
  for (const bad of ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tTAB", "\rCR", "  =HYPERLINK(\"x\")", "\t =x", " @x", "-cmd|' /C calc'!A0"]) {
    const out = X.csvCell(bad);
    assert.ok(out.replace(/^"/, "").startsWith("'"), `${JSON.stringify(bad)} -> ${JSON.stringify(out)}`);
  }
  assert.equal(X.csvCell("=1+1"), "'=1+1");
  assert.equal(X.csvCell("=a,b"), "\"'=a,b\"");
  assert.equal(X.csvCell("  =x"), "'  =x");
  // not formulas: untouched
  for (const ok of ["plain", "a=b", "x-1", "72 °F", "", "mail@x", "'=already"]) assert.equal(X.csvCell(ok), ok);
});

test("csvCell keeps numbers numeric, including negative samples", () => {
  assert.equal(X.csvCell(-3.2), "-3.2");
  assert.equal(X.csvCell(0), "0");
  assert.equal(X.csvCell(1e-7), "1e-7");
  assert.equal(X.csvCell("-3.2"), "-3.2");        // plain numeric text cannot run anything
  assert.equal(X.csvCell("+5"), "'+5");
});

test("toCsv neutralises malicious point and equip names in the header, not the data", () => {
  const evil = [
    { uuid: "u1", equip: "=cmd|' /C calc'!A0", dis: "Temp", unit: "°F" },
    { uuid: "u2", equip: "AHU", dis: "@SUM(1+1)", unit: "" },
    { uuid: "u3", equip: "+1", dis: "-2", unit: "" },
  ];
  const data = new Map([["u1", new Map([[t(12), -3.2]])], ["u2", new Map([[t(12), 5]])], ["u3", new Map([[t(12), -0.5]])]]);
  const { csv } = X.toCsv({ columns: evil, data, mode: "stored", system: "si" });
  const [head, row] = csv.slice(1).split("\r\n");
  const cells = head.split(",");
  assert.equal(cells[2], "'=cmd|' /C calc'!A0 Temp [°F]");
  assert.equal(cells[3], "AHU @SUM(1+1)");   // starts with "AHU": not a formula
  assert.equal(cells[4], "'+1 -2");
  assert.ok(row.endsWith(",-3.2,5,-0.5"), row);
});

test("export locks before resolving its range and restores state when that lookup fails", async () => {
  const saved = new Map();
  const globals = ["document", "renderRangeControl", "getChartRangeState", "resolveChartSelection", "chartTimeZone", "ofddUnits", "esc"];
  for (const key of globals) saved.set(key, { had: Object.hasOwn(globalThis, key), value: globalThis[key] });
  const listeners = new Map(), elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: id === "exUnits" ? "display" : id === "exRes" ? "15m" : "",
      options: [{ textContent: "" }], classList: { toggle() {} },
      addEventListener(type, fn) { listeners.set(id + ":" + type, fn); },
    });
    return elements.get(id);
  };
  const gates = [];
  try {
    globalThis.document = { getElementById: element };
    globalThis.renderRangeControl = () => {};
    globalThis.getChartRangeState = () => ({ preset: "all" });
    globalThis.chartTimeZone = () => "UTC";
    globalThis.ofddUnits = { displaySystem: () => "si", display: () => ({ unit: "" }) };
    globalThis.esc = (x) => String(x);
    globalThis.resolveChartSelection = () => new Promise((resolve, reject) => gates.push({ resolve, reject }));
    const equip = { name: "AHU-1", attrs: { id: "eq-1", siteRef: "site-a", dis: "AHU-1", markers: "ahu,equip" } };
    const point = { uuid: "p1", tags: ["point", "his"], siteRef: "site-a", kind: "Number", units: "", dis: "point", equipRef: "eq-1" };
    X.render({ model: { sites: [{ name: "site-a", attrs: { id: "site-a" } }], equips: [equip], points: [point] }, scope: { site: "site-a", equip: "eq-1" } });
    await new Promise(setImmediate);
    gates[0].resolve({ resolvedBounds: { fromMs: 1000, toMs: 3600e3 } });
    await new Promise(setImmediate);

    const go = element("exGo");
    listeners.get("exGo:click")();
    assert.equal(go.disabled, true);
    listeners.get("exGo:click")();
    assert.equal(gates.length, 2);
    gates[1].reject(new Error("range endpoint failed"));
    await new Promise(setImmediate);
    assert.match(element("exStatus").textContent, /range endpoint failed/);
    assert.equal(go.disabled, false, "button is restored after a failed preflight");
  } finally {
    for (const [key, prior] of saved) {
      if (prior.had) globalThis[key] = prior.value;
      else delete globalThis[key];
    }
  }
});

import { readFileSync } from "node:fs";

test("methodFor handles fault_timeline, ruleRef, String and Enum correctly", () => {
  assert.equal(X.methodFor({ kind: "Number", tags: ["point", "his", "fault_timeline"] }), "MAX");
  assert.equal(X.methodFor({ kind: "Number", tags: ["point", "his"], rec: { attrs: { ruleRef: "VAV-1" } } }), "MAX");
  assert.equal(X.methodFor({ kind: "String", tags: ["point", "his"] }), "LAST");
  assert.equal(X.methodFor({ kind: "Enum", tags: ["point", "his"] }), "LAST");
});

test("exportCandidates isolates single equip, separates per-sensor faults, includes current-only, rejects site-wide fail-open", () => {
  const model = {
    sites: [{ name: "Site A", attrs: { id: "site-a" } }],
    equips: [
      { name: "AHU-1", attrs: { id: "ahu-1", siteRef: "site-a", dis: "AHU-1", markers: "ahu,equip" } },
      { name: "AHU-2", attrs: { id: "ahu-2", siteRef: "site-a", dis: "AHU-2", markers: "ahu,equip" } },
    ],
    devices: [],
    points: [
      { uuid: "sat", name: "SAT", dis: "Supply Air Temp", kind: "Number", units: "°F", tags: ["point", "sensor", "his"], siteRef: "site-a", equipRef: "ahu-1" },
      { uuid: "sat-2", name: "SAT2", dis: "Supply Air Temp", kind: "Number", units: "°F", tags: ["point", "sensor", "his"], siteRef: "site-a", equipRef: "ahu-1" },
      { uuid: "mode", name: "Mode", dis: "Mode", kind: "String", units: "", tags: ["point", "his"], siteRef: "site-a", equipRef: "ahu-1" },
      { uuid: "fan", name: "Fan", dis: "Fan Status", kind: "Bool", units: "", tags: ["point", "sensor", "his"], siteRef: "site-a", equipRef: "ahu-1" },
      { uuid: "cur-only", name: "CurOnly", dis: "Manual Override", kind: "Bool", units: "", tags: ["point", "cmd"], siteRef: "site-a", equipRef: "ahu-1" },
      { uuid: "oat-w", name: "OAT", dis: "Weather OAT", kind: "Number", units: "°F", tags: ["point", "weather", "his"], siteRef: "site-a", weatherStationRef: "ws-1" },
      { uuid: "wrong-eq", name: "Other", dis: "Other SAT", kind: "Number", units: "°F", tags: ["point", "sensor", "his"], siteRef: "site-a", equipRef: "ahu-2" },
      { uuid: "wrong-site", name: "BadSite", dis: "Bad Site", kind: "Number", units: "°F", tags: ["point", "sensor", "his"], siteRef: "site-b", equipRef: "ahu-1" },
      { uuid: "tl-1", name: "TL1", dis: "SV-RANGE timeline", kind: "Number", units: "", tags: ["point", "his", "fault_timeline"], siteRef: "site-a", equipRef: "ahu-1", rec: { attrs: { ruleRef: "SV-RANGE", sensorRef: "sat" } } },
      { uuid: "tl-2", name: "TL2", dis: "SV-RANGE timeline", kind: "Number", units: "", tags: ["point", "his", "fault_timeline"], siteRef: "site-a", equipRef: "ahu-1", rec: { attrs: { ruleRef: "SV-RANGE", sensorRef: "sat-2" } } },
      { uuid: "sum-1", name: "SUM1", dis: "SV-RANGE", kind: "Number", units: "h", tags: ["point", "his", "fdd", "fault"], siteRef: "site-a", equipRef: "ahu-1", rec: { attrs: { ruleRef: "SV-RANGE", fddOutput: "fault_hours", fddOutputSince: "2026-11-05T12:15:00Z" } } },
    ],
  };

  assert.equal(X.exportCandidates(model, { site: "site-a", equip: "" }).columns.length, 0, "must never fail open to site");
  assert.equal(X.exportCandidates(model, { site: "site-a", equip: "__weather__" }).columns.length, 0);

  const inv = X.exportCandidates(model, { site: "site-a", equip: "ahu-1" });
  assert.equal(inv.equipLabel, "AHU-1");
  assert.equal(inv.ioPoints.length, 5);
  assert.equal(inv.fddPoints.length, 3);
  assert.equal(inv.currentOnly.length, 1);
  assert.equal(inv.currentOnly[0].uuid, "cur-only");
  assert.ok(!inv.columns.some((c) => ["oat-w", "wrong-eq", "wrong-site"].includes(c.uuid)));
  assert.equal(inv.fddPoints.filter((c) => c.lane === "fault_timeline").length, 2);
  assert.equal(inv.fddPoints.find((c) => c.uuid === "sum-1").fddOutputSinceMs, Date.parse("2026-11-05T12:15:00Z"));
});

test("collectJoined + toJoinedCsv join exact raw timestamps, preserve types/0/false, neutralize formulas, enforce fddOutputSince", async () => {
  const columns = [
    { uuid: "sat", equip: "AHU-1", dis: "SAT", unit: "°F", kind: "Number", historyAvailable: true, point: { uuid: "sat", kind: "Number", tags: ["point", "his"] } },
    { uuid: "mode", equip: "AHU-1", dis: "Mode", unit: "", kind: "String", historyAvailable: true, point: { uuid: "mode", kind: "String", tags: ["point", "his"] } },
    { uuid: "fan", equip: "AHU-1", dis: "Fan", unit: "", kind: "Bool", historyAvailable: true, point: { uuid: "fan", kind: "Bool", tags: ["point", "his"] } },
    { uuid: "cur", equip: "AHU-1", dis: "CurOnly", unit: "", kind: "Bool", historyAvailable: false, point: { uuid: "cur", kind: "Bool", tags: ["point"] } },
    { uuid: "sum", equip: "AHU-1", dis: "SV-RANGE · fault_hours", unit: "h", kind: "Number", historyAvailable: true, fddOutputSinceMs: t(12, 15), point: { uuid: "sum", kind: "Number", tags: ["point", "his", "fdd"] } },
  ];
  const apiFn = async (url) => {
    assert.ok(!url.includes("window="), "raw join must omit window=");
    return {
      data: [
        { uuid: "sat", values: [{ ts: new Date(t(12)).toISOString(), double: 0 }, { ts: new Date(t(12, 15)).toISOString(), double: 72.5 }] },
        { uuid: "mode", values: [{ ts: new Date(t(12)).toISOString(), characterString: "=CMD()" }, { ts: new Date(t(12, 15)).toISOString(), characterString: "COOL" }] },
        { uuid: "fan", values: [{ ts: new Date(t(12)).toISOString(), boolean: false }, { ts: new Date(t(12, 15)).toISOString(), boolean: true }] },
        { uuid: "sum", values: [{ ts: new Date(t(12)).toISOString(), double: 99 }, { ts: new Date(t(12, 15)).toISOString(), double: 0.25 }] },
      ],
    };
  };
  const joined = await X.collectJoined({ columns, startMs: t(12), endMs: t(12, 30), apiFn });
  assert.equal(joined.mode, "raw");
  const { csv, rows } = X.toJoinedCsv({ columns, data: joined.data, startMs: t(12), endMs: t(12, 30), mode: joined.mode });
  assert.equal(rows, 2);
  const lines = csv.slice(1).split("\r\n");
  assert.equal(lines[1], `${X.localIso(t(12))},2026-11-05T12:00:00.000Z,0,'=CMD(),false,,`, "pre-fddOutputSince sample dropped, 0/false/formula preserved, current-only blank");
  assert.equal(lines[2], `${X.localIso(t(12, 15))},2026-11-05T12:15:00.000Z,72.5,COOL,true,,0.25`);
});

test("collectJoined subdivides chunks hitting 10k sample cap and falls back to aligned buckets with empty gaps", async () => {
  const col = { uuid: "p1", equip: "AHU-1", dis: "SAT", unit: "°F", kind: "Number", historyAvailable: true, point: { uuid: "p1", kind: "Number", tags: ["point", "his"] } };
  const tl = { uuid: "tl", equip: "AHU-1", dis: "TL", unit: "0/1", kind: "Number", historyAvailable: true, point: { uuid: "tl", kind: "Number", tags: ["point", "his", "fault_timeline"] } };
  let rawCalls = 0, bucketCalls = 0;
  const many = Array.from({ length: 10000 }, (_, i) => ({ ts: new Date(t(12) + i * 10).toISOString(), double: 70 }));
  const apiFn = async (url) => {
    if (!url.includes("window=")) {
      rawCalls++;
      return { data: [{ uuid: "p1", values: many }] };
    }
    bucketCalls++;
    const q = new URL(url, "http://x").searchParams;
    const ids = q.getAll("uuids");
    if (ids.includes("tl")) assert.equal(q.get("method"), "MAX");
    return { data: ids.map((u) => ({ uuid: u, values: [{ ts: new Date(t(12)).toISOString(), double: u === "tl" ? 1 : 71 }] })) };
  };
  const res = await X.collectJoined({ columns: [col, tl], startMs: t(12), endMs: t(12, 15), apiFn });
  assert.ok(rawCalls >= 2, "subdivided after 10k hit");
  assert.ok(bucketCalls >= 2, "fell back to aligned buckets");
  assert.equal(res.mode, "bucketed");
  const { rows, csv } = X.toJoinedCsv({ columns: [col, tl], data: res.data, startMs: t(12), endMs: t(12, 15), windowSec: res.windowSec, mode: res.mode });
  assert.equal(rows, 3, "emits aligned 5-min grid rows including missing gaps");
  assert.match(csv, /2026-11-05T12:10:00\.000Z,,/);
});

test("collectJoined fills older uncovered range from Timescale and surfaces truncation loudly", async () => {
  const startMs = Date.UTC(2026, 10, 1, 0, 0);
  const midMs = Date.UTC(2026, 10, 4, 0, 0);
  const endMs = Date.UTC(2026, 10, 5, 0, 0);
  const cols = [
    { uuid: "sat", equip: "AHU-1", dis: "SAT", unit: "°F", kind: "Number", historyAvailable: true, point: { uuid: "sat", kind: "Number", tags: ["point", "his"] } },
    { uuid: "mode", equip: "AHU-1", dis: "Mode", unit: "", kind: "String", historyAvailable: true, point: { uuid: "mode", kind: "String", tags: ["point", "his"] } },
  ];
  const apiFn = async () => ({
    data: [{ uuid: "sat", values: [{ ts: new Date(midMs).toISOString(), double: 72 }] }],
  });
  const timescaleFn = async ({ uuids, fromMs, toMs }) => {
    assert.deepEqual(uuids, ["sat"]);
    assert.equal(fromMs, startMs);
    assert.equal(toMs, midMs);
    return {
      ok: true,
      bucket: "5 minutes",
      rows: [{ point_uuid: "sat", bucket: new Date(startMs).toISOString(), avg: 68.5, max: 69, n: 1 }],
    };
  };
  const res = await X.collectJoined({ columns: cols, startMs, endMs, apiFn, timescaleFn });
  assert.equal(res.mode, "mixed");
  assert.equal(res.timescaleUsed, true);
  assert.deepEqual(res.timescaleSkippedCols, ["Mode"]);
  assert.equal(res.data.get("sat").get(startMs), 68.5);
  assert.equal(res.data.get("sat").get(midMs), 72);

  await assert.rejects(
    X.collectJoined({
      columns: cols,
      startMs,
      endMs,
      apiFn,
      timescaleFn: async () => ({ ok: true, truncated: true, rows: [] }),
    }),
    /truncated|limit/i,
  );
});

test("Export HTML has single-device simplified controls and no checkbox/filter/unit clutter", () => {
  const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
  assert.match(html, /id="exGo"[^>]*>Download CSV</);
  assert.match(html, /id="exRangeControl"/);
  assert.match(html, /id="exSummary"/);
  for (const oldId of ["exRes", "exUnits", "exFilter", "exAll", "exNone", "exList"]) {
    assert.ok(!html.includes(`id="${oldId}"`), `removed legacy #${oldId}`);
  }
});
