import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../static/charts.js", import.meta.url), "utf8");
const scheduleSource = readFileSync(new URL("../static/schedule.js", import.meta.url), "utf8");
function context(search = "") {
  const state = { href: `https://nf.example.test/app/${search ? `?${search}` : ""}`, search: search ? `?${search}` : "" };
  const ctx = vm.createContext({ URL, URLSearchParams, Intl, Date, Math, Object, Number, String, Map, Set,
    location: state, history: { pushState(_s, _t, href) { state.href = String(href); state.search = new URL(href).search; }, replaceState(_s, _t, href) { state.href = String(href); state.search = new URL(href).search; } } });
  vm.runInContext(scheduleSource, ctx, { filename: "schedule.js" });
  vm.runInContext(source, ctx, { filename: "charts.js" });
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
}

test("range presets resolve to the expected elapsed intervals and All uses oldest history", () => {
  const c = context(), resolve = c.get("resolveChartRange"), now = Date.UTC(2026, 10, 10, 12);
  for (const [preset, hours] of [["1h", 1], ["24h", 24], ["1w", 168]]) {
    const r = resolve({ preset }, { nowMs: now });
    assert.equal(r.toMs - r.fromMs, hours * 3600e3);
    assert.equal(r.toMs, now);
  }
  assert.deepEqual({ ...resolve({ preset: "all" }, { nowMs: now, oldestMs: now - 1234567 }) }, { fromMs: now - 1234567, toMs: now });
  assert.deepEqual({ ...resolve({ preset: "custom", fromMs: now - 5000, toMs: now - 1000 }, { nowMs: now }) }, { fromMs: now - 5000, toMs: now - 1000 });
});

test("chart range URL state restores custom bounds and malformed links fall back to All", () => {
  const c = context("range.points=custom&from.points=1794300000000&to.points=1794303600000");
  assert.deepEqual({ ...c.get("getChartRangeState")("points") }, { preset: "custom", fromMs: 1794300000000, toMs: 1794303600000 });
  c.get("setChartRangeState")("points", { preset: "1w" });
  assert.equal(c.get("getChartRangeState")("points").preset, "1w");
  const invalid = context("range.points=custom&from.points=bad&to.points=100");
  assert.deepEqual({ ...invalid.get("getChartRangeState")("points") }, { preset: "all" });
  const backwards = context("range.points=custom&from.points=200&to.points=100");
  assert.deepEqual({ ...backwards.get("getChartRangeState")("points") }, { preset: "all" });
});

test("custom chart dates use the site timezone wall clock", () => {
  const c = context();
  assert.equal(c.get("chartTimeZone")("not a timezone"), "UTC");
  const display = c.get("dateTimeInputValue")(Date.UTC(2026, 0, 1, 12), "America/Chicago");
  assert.equal(display, "2026-01-01T06:00");
  assert.ok(Number.isNaN(c.get("dateTimeInputMs")("2026-03-08T02:30", "America/Chicago")), "rejects a skipped DST wall time");
  assert.equal(Number.isFinite(c.get("dateTimeInputMs")("2026-03-08T03:30", "America/Chicago")), true);
});

test("All range discovery and history reads stay in 40 UUID, count-bounded requests", async () => {
  const c = context(), calls = [];
  c.api = async (path) => {
    calls.push(path);
    const q = new URL(path, "https://nf.example.test").searchParams;
    const uuids = q.getAll("uuids");
    if (q.has("count") && q.get("count") === "1") return { data: uuids.map((uuid) => ({ uuid, values: [{ ts: "2026-11-01T00:00:00Z", double: 1 }] })) };
    return { data: uuids.map((uuid) => ({ uuid, values: [{ ts: "2026-11-01T00:00:00Z", double: 2 }] })) };
  };
  const points = Array.from({ length: 41 }, (_, i) => ({ uuid: `p-${String(i).padStart(36, "0")}` }));
  const result = await c.get("fetchRange")(points, { preset: "all" }, { nowMs: Date.parse("2026-11-02T00:00:00Z"), target: 72 });
  assert.equal(result.series.size, points.length);
  assert.equal(result.fromMs, Date.parse("2026-11-01T00:00:00Z"));
  assert.equal(calls.length, 4); // two oldest-discovery + two data batches
  for (const path of calls) {
    assert.ok(path.length <= 6000);
    assert.ok(new URL(path, "https://nf.example.test").searchParams.getAll("uuids").length <= 40);
  }
  assert.ok(calls.some((p) => new URL(p, "https://nf.example.test").searchParams.get("count") === "1"));
  assert.ok(calls.some((p) => new URL(p, "https://nf.example.test").searchParams.get("count") === "10000"));
});

test("All discovery caches successful chunks only and retries a failed chunk", async () => {
  const c = context(), calls = [];
  let failUuid = "p-40";
  c.api = async (path) => {
    calls.push(path);
    const q = new URL(path, "https://nf.example.test").searchParams, uuids = q.getAll("uuids");
    if (q.get("count") === "1") {
      if (uuids.includes(failUuid)) { failUuid = null; throw new Error("temporary oldest lookup failure"); }
      return { data: uuids.map((uuid) => ({ uuid, values: [{ ts: "2026-11-01T00:00:00Z" }] })) };
    }
    return { data: [] };
  };
  const points = Array.from({ length: 41 }, (_, i) => ({ uuid: `p-${i}` }));
  await assert.rejects(c.get("fetchRange")(points, { preset: "all" }), /temporary oldest lookup failure/);
  const firstAttempt = calls.filter((x) => new URL(x, "https://nf.example.test").searchParams.get("count") === "1");
  assert.equal(firstAttempt.length, 2);
  const result = await c.get("fetchRange")(points, { preset: "all" });
  const totalOldestReads = calls.filter((x) => new URL(x, "https://nf.example.test").searchParams.get("count") === "1");
  assert.equal(totalOldestReads.length, 3, "the completed chunk stays cached; only the failed chunk retries");
  assert.equal(result.fromMs, Date.parse("2026-11-01T00:00:00Z"));
});

test("multi-page range merges duplicate boundary timestamps, preferring the later page", async () => {
  const c = context();
  let boundary, dataPage = 0;
  c.api = async (path) => {
    const q = new URL(path, "https://nf.example.test").searchParams;
    if (q.get("count") === "1") return { data: [] };
    dataPage++;
    if (dataPage === 1) boundary = Date.parse(q.get("to"));
    return { data: [{ uuid: "p1", values: [{ ts: new Date(boundary).toISOString(), double: dataPage }] }] };
  };
  const toMs = Date.parse("2026-11-10T00:00:00Z"), fromMs = toMs - 8 * 86400000;
  const result = await c.get("fetchRange")([{ uuid: "p1" }], { preset: "custom", fromMs, toMs },
    { windowSec: 60, minWindowSec: 60, preserveWindow: true });
  assert.equal(dataPage, 2);
  assert.deepEqual(Array.from(result.series.get("p1"), (row) => Array.from(row)), [[boundary, 2]]);
});

test("custom range includes clipped edge buckets and sends exact endpoints", async () => {
  const c = context(), fromMs = Date.parse("2026-11-01T01:02:00Z"), toMs = Date.parse("2026-11-01T01:04:00Z");
  let dataUrl;
  c.api = async (path) => {
    dataUrl = path;
    return { data: [{ uuid: "p1", values: [{ ts: "2026-11-01T01:00:00Z", double: 3 }] }] };
  };
  const result = await c.get("fetchRange")([{ uuid: "p1" }], { preset: "custom", fromMs, toMs }, { windowSec: 300, minWindowSec: 300 });
  const q = new URL(dataUrl, "https://nf.example.test").searchParams;
  assert.equal(Date.parse(q.get("from")), fromMs);
  assert.equal(Date.parse(q.get("to")), toMs);
  assert.deepEqual(Array.from(result.series.get("p1"), (x) => Array.from(x)), [[fromMs, 3]]);
});
