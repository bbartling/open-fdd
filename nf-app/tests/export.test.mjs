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
