// #1643: Overview fetches plant, run hours and zone temperatures only. Scatter, economizer,
// per-AHU timeseries, VAV plots and energy stay off that request. A modest synthetic site
// stays within 12 history GETs, a later card reuses the prefetch, and a tab change aborts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dashboardModel } from "./fixtures/dashboard_model.mjs";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

function load() {
  const gets = [];
  let hang = null;
  const ctx = vm.createContext({
    console, URLSearchParams, TextDecoder, atob, btoa, Date, Math, Map, Set, Promise, DOMException,
    localStorage: { getItem: () => null, setItem() {} },
    AbortController,
  });
  ctx.FAULT_LANE = { lineStyle: { color: "red" }, areaStyle: { color: "red" } };
  ctx.pickWindow = () => 3600;
  ctx.ofddChart = () => ({}); ctx.ofddRender = () => {};
  for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "schedule.js", "charts.js", "rcx.js", "plot-spec-data.js", "rcx-overview.js", "rcx-presets.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  let entered = () => {};
  ctx.api = async (path, _body, opts = {}) => {
    if (opts.signal && opts.signal.aborted) throw new DOMException("aborted", "AbortError");
    if (hang) {
      entered();
      await new Promise((resolve, reject) => {
        if (opts.signal.aborted) { reject(new DOMException("aborted", "AbortError")); return; }
        opts.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    }
    gets.push(String(path));
    const uuids = [...String(path).matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
    return { data: uuids.map((uuid) => ({ uuid, values: [{ ts: "2026-11-05T12:00:00.000Z", double: 1 }] })) };
  };
  ctx.gets = gets;
  ctx.hang = (on) => { hang = on; };
  ctx.whenEntered = new Promise((resolve) => { entered = resolve; });
  ctx.get = (n) => vm.runInContext(n, ctx);
  return ctx;
}

function modelOf(ctx) {
  const { records, points } = dashboardModel({ plant: "full" });
  const extra = [
    ["HP-1", "heatPump"],
    ["RTU-1", "rtu"],
    ["FCU-1", "fcu"],
  ];
  for (const [id, marker] of extra) {
    records.push({ uuid: `eq-${id}`, name: id, pointType: "EQUIPMENT", attrs: { id, dis: id, siteRef: "site-a", markers: `equip,${marker}` } });
    points.push({ uuid: `pt-${id}-zone-temp`, name: "zone-temp", pointType: "POINT", attrs: {
      siteRef: "site-a", equipRef: id, dis: `${id} zone-temp`, markers: "point,his,cur,zone,air,temp,sensor",
      class: "zone-air-temp-sensor", kind: "Number", unit: "°C",
    } });
  }
  return {
    sites: records.filter((r) => r.pointType === "SITE"),
    equips: records.filter((r) => r.pointType === "EQUIPMENT"),
    devices: [],
    points: points.map(ctx.toPoint),
  };
}

test("Overview plan is plant and every zone temperature; heavy plots are Analytics", () => {
  const ctx = load();
  const model = modelOf(ctx);
  const overview = ctx.rcxPlan(model.equips, model, catalog, { tab: "rcx", single: false, place: "overview" });
  const ids = new Set(overview.ready.map((x) => x.view.id));
  for (const id of ["economizer-delta", "ahu_dats", "ahu_mats", "fan_speeds", "duct_static_ts", "vav_positions", "vav_health", "hw_reset_scatter"]) {
    assert.ok(!ids.has(id), `${id} is not on Overview`);
  }
  const zones = overview.ready.find((x) => x.view.id === "zone_temps");
  assert.ok(zones, "zone temperatures are on Overview");
  const names = zones.equips.map((e) => e.name).sort();
  for (const id of ["VAV-1", "HP-1", "RTU-1", "FCU-1"]) assert.ok(names.includes(id), `${id} zone temp is included`);
  const more = new Set(ctx.rcxPlan(model.equips, model, catalog, { tab: "rcx", single: false, place: "more" }).ready.map((x) => x.view.id));
  assert.ok(more.has("ahu_dats") && more.has("hw_reset_scatter") && more.has("vav_positions"));
  assert.equal(ctx.rcxPlan(model.equips, model, catalog, { tab: "rcx", single: false }).ready.length,
    overview.ready.length + more.size, "omitting place still plans every view");
});

test("a modest Overview prefetch stays within 12 history reads, and a card reuses them", async () => {
  const ctx = load();
  const model = modelOf(ctx);
  const { ready } = ctx.rcxPlan(model.equips, model, catalog, { tab: "rcx", single: false, place: "overview" });
  const now = Date.parse("2026-11-20T00:00:00Z");
  const range = { preset: "7d", resolvedBounds: { fromMs: now - 7 * 86400e3, toMs: now } };
  const fine = new Map(), disp = new Map();
  for (const card of ready) {
    const dest = card.view.fine ? fine : disp;
    for (const eq of card.equips) for (const pts of Object.values(eq.bound || {})) {
      for (const p of pts || []) if (p && p.uuid) dest.set(p.uuid, p);
    }
  }
  if (disp.size) await ctx.fetchRange([...disp.values()], range, { siteTz: "UTC", preserveWindow: true, nowMs: now });
  if (fine.size) await ctx.fetchRange([...fine.values()], range, { siteTz: "UTC", preserveWindow: true, windowSec: 300, minWindowSec: 300, nowMs: now });
  const historyGets = ctx.gets.filter((u) => u.includes("/api/v1/point/data") && u.includes("window="));
  assert.ok(disp.size > 0, "Overview has display-grid points");
  assert.ok(historyGets.length > 0 && historyGets.length <= 12, `history GETs ${historyGets.length}`);
  const windowSec = Number(historyGets[0].match(/window=(\d+)s/)[1]);
  const before = ctx.gets.length;
  const sample = [...disp.values()].slice(0, 2);
  await ctx.fetchSeries(sample, 168, { method: "AVERAGE", windowSec, endMs: now, fromMs: now - 7 * 86400e3 });
  assert.equal(ctx.gets.length, before, "a card whose points were prefetched does not fetch again");
});

test("cancelHistory aborts an in-flight history read", async () => {
  const ctx = load();
  ctx.hang(true);
  const point = { uuid: "p1" };
  const pending = ctx.fetchSeries([point], 1, { windowSec: 300, endMs: 1_700_000_000_000, fromMs: 1_699_000_000_000 });
  await ctx.whenEntered;
  ctx.cancelHistory();
  await assert.rejects(pending, (e) => e && e.name === "AbortError");
});
