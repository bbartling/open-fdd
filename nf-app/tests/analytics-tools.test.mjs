// node --test nf-app/tests/analytics-tools.test.mjs
// 5.0.3 acceptance: the read-only agent analytics hook (hooks/analytics.js) on the synthetic two-site fixture
// (tests/fixtures/two_site.mjs, `fakeSdkHttp`). Every tool is compared with the fixture TRUTH, every row is keyed by
// equipUuid, and the hook cannot write.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { twoSite as fx, TRUTH, wall, confirmedLane, resample, fakeSdkHttp } from "./fixtures/two_site.mjs";

const require = createRequire(import.meta.url);
const analytics = require("../hooks/analytics.js");
const fddHook = require("../hooks/fdd.js");

const A = fx.sites["site-a"], B = fx.sites["site-b"];
const NOW = Math.max(A.endMs, B.endMs);            // the fixture ends here; the hook's clock is pinned to it
const DAYS = 29;                                    // 696 h: covers the 28 d the fixture holds (A is one DST hour longer than 672 h)
const near = (a, b, msg, eps = 1e-3) => assert.ok(Math.abs(a - b) < eps, `${msg}: ${a} vs ${b}`);

// ---- the fixture NF: model + history + the FDD hook's fault timeline points ----------------------------------------------
const timeline = new Map();                         // uuid -> [[ms, 1|0]] (what hooks/fdd.js writes: assessed timestamps only)
const timelineRecs = [];
for (const s of [A, B]) {
  const key = fddHook.resultKey(s.equipRec, s.id, "AHU-1");
  const uuid = fddHook.timelineUuid(key, "CMD-1");
  timelineRecs.push({ uuid, name: `${s.id} CMD-1 timeline`, layer: "default", pointType: "POINT", attrs: {
    dis: "CMD-1 timeline", markers: "point,his,fault_timeline", equipRef: "AHU-1", siteRef: s.id, ruleRef: "CMD-1", equipUuid: s.equipUuid, unit: "", kind: "Number" } });
  timeline.set(uuid, confirmedLane(s.rows).filter(([, v]) => v != null));
}

/** fakeSdkHttp + timeline points (served on the default layer of their site, history from `timeline`). */
function nfHttp() {
  const base = fakeSdkHttp(fx);
  const writes = base.writes;
  return {
    writes, calls: [],
    async post(p, body) {
      this.calls.push(["POST", p]);
      const r = await base.post(p, body);
      if (p === "/api/v1/point/query" && body.layer !== "model") {
        const site = body.structuredQuery && body.structuredQuery.field && body.structuredQuery.field.text;
        return { data: { points: [...r.data.points, ...timelineRecs.filter((x) => !site || x.attrs.siteRef === site)] } };
      }
      return r;
    },
    async get(p) {
      this.calls.push(["GET", p]);
      const r = await base.get(p);
      if (!p.startsWith("/api/v1/point/data?")) return r;
      const q = new URLSearchParams(p.split("?")[1]);
      const win = parseInt(q.get("window") || "0", 10) || null, from = Date.parse(q.get("from")), to = Date.parse(q.get("to"));
      for (const uuid of q.getAll("uuids")) {
        if (!timeline.has(uuid)) continue;
        r.data.data.push({ uuid, values: resample(timeline.get(uuid), from, to, win, q.get("method") || "AVERAGE").map(([ms, v]) => ({ ts: new Date(ms).toISOString(), double: v })) });
      }
      return r;
    },
  };
}

/** Run the hook once: returns the result (and the logged lines). */
async function run(args, { http = nfHttp(), now = NOW } = {}) {
  const logs = [];
  const result = await analytics.handle({ sdk: { http, logEvent: (m) => logs.push(m) }, args, now: () => now });
  return { result, logs, http };
}
const ok = async (args, o) => { const r = await run(args, o); assert.equal(r.result.ok, true, JSON.stringify(r.result).slice(0, 400)); return r; };

// ---- 1. weekly runtime -----------------------------------------------------------------------------------------------------
test("analyze_ahu_weekly_runtime: per (siteRef, equipUuid) ISO week equals TRUTH, the two AHU-1 never share a row", async () => {
  const { result, logs } = await ok({ tool: "analyze_ahu_weekly_runtime", days: DAYS });
  assert.equal(result.grid_s, 300);
  const rows = result.rows;
  assert.deepEqual([...new Set(rows.map((r) => r.equipUuid))].sort(), [A.equipUuid, B.equipUuid].sort(), "distinct equipUuid keys");
  assert.ok(rows.every((r) => r.equipRef === "AHU-1" && r.siteRef === (r.equipUuid === A.equipUuid ? "site-a" : "site-b")), "siteRef follows the uuid");
  for (const [S, id] of [[A, "site-a"], [B, "site-b"]]) {
    const mine = rows.filter((r) => r.equipUuid === S.equipUuid);
    assert.equal(mine.length, 4, `${id}: four ISO weeks`);
    TRUTH[id].weeks.forEach((w, k) => {
      const r = mine[k];
      assert.equal(r.week_start, new Date(S.weekStarts[k]).toISOString(), `${id} week ${k} starts at the local Monday`);
      near(r.run_hours, w.runHours, `${id} w${k} run_hours`);
      near(r.in_schedule_hours, w.inScheduleHours, `${id} w${k} in_schedule_hours`);
      near(r.after_hours, w.afterHoursHours, `${id} w${k} after_hours`);
      near(r.schedule_hours, w.scheduleHours, `${id} w${k} schedule_hours`);
      assert.equal(r.partial_week, false, `${id} w${k} is a full week`);
      assert.ok(Number.isFinite(r.mean_oat_on_c), "mean OAT while on, in degC");
      assert.equal(r.signal_role, "fan_status");
    });
  }
  const a = rows.filter((r) => r.equipUuid === A.equipUuid), b = rows.filter((r) => r.equipUuid === B.equipUuid);
  // site-a: after-hours = the 70 min pulse + the 10 h holiday run; schedule hours step down in the holiday week
  assert.deepEqual(a.map((r) => r.schedule_hours), [50, 40, 50, 50]);
  near(a.reduce((x, r) => x + r.after_hours, 0), TRUTH["site-a"].afterHoursFanHours, "site-a after-hours total");
  assert.ok(a[1].after_hours >= 10 && a[0].after_hours > 1 && a[0].after_hours < 1.5, "holiday week >= 10 h; the pulse is 70 min, not smeared to 2 h");
  assert.ok(a.every((r) => r.schedule_source === "schedule") && /NF schedule/.test(a[0].schedule_label));
  // site-b: no bound schedule -> the 4.x default calendar, zero after-hours
  assert.deepEqual(b.map((r) => r.schedule_hours), [50, 50, 50, 50]);
  assert.ok(b.every((r) => r.after_hours === 0 && r.schedule_source === "default" && /50 h\/week \(default\)/.test(r.schedule_label)));
  // the answer is also one logged JSON line
  assert.equal(logs.length, 1);
  assert.deepEqual(JSON.parse(logs[0]).rows.length, rows.length);
});

test("analyze_ahu_weekly_runtime: filters by site and equip; a Haystack id alone returns both, each under its own uuid", async () => {
  const bySite = (await ok({ tool: "analyze_ahu_weekly_runtime", site: "site-b", days: DAYS })).result.rows;
  assert.ok(bySite.length && bySite.every((r) => r.siteRef === "site-b" && r.equipUuid === B.equipUuid));
  const byUuid = (await ok({ tool: "analyze_ahu_weekly_runtime", equipUuid: A.equipUuid, days: DAYS })).result.rows;
  assert.ok(byUuid.length && byUuid.every((r) => r.equipUuid === A.equipUuid));
  const both = (await ok({ tool: "analyze_ahu_weekly_runtime", equip: "AHU-1", days: DAYS })).result.rows;
  assert.equal(new Set(both.map((r) => r.equipUuid)).size, 2);
  const bad = (await run({ tool: "analyze_ahu_weekly_runtime", site: "nope" })).result;
  assert.equal(bad.ok, false);
  assert.match(bad.error, /unknown site/);
});

// ---- 2. mechanical cooling ---------------------------------------------------------------------------------------------------
test("analyze_mechanical_cooling: the <10 degC bin is the 20 min event (1/3 h); every bin equals TRUTH on the fine grid", async () => {
  const { result } = await ok({ tool: "analyze_mechanical_cooling", days: DAYS });
  assert.equal(result.edges_c.length, 5);
  assert.deepEqual([...new Set(result.rows.map((r) => r.equipUuid))].sort(), [A.equipUuid, B.equipUuid].sort());
  for (const [S, id] of [[A, "site-a"], [B, "site-b"]]) {
    const rows = result.rows.filter((r) => r.equipUuid === S.equipUuid);
    assert.equal(rows.length, 1, `${id}: one compressor row`);
    const r = rows[0];
    assert.equal(r.signal_role, "compressor_status");
    assert.equal(r.bins.length, 6);
    assert.deepEqual(r.bins.map((b) => b.label), ["<10", "10-16", "16-21", "21-27", "27-32", ">=32"]);
    TRUTH[id].cooling.binHours.forEach((h, i) => near(r.bins[i].hours, h, `${id} bin ${r.bins[i].label}`));
    near(r.total_hours, TRUTH[id].cooling.binHours.reduce((a, b) => a + b, 0), `${id} total`);
  }
  near(result.rows.find((r) => r.equipUuid === A.equipUuid).bins[0].hours, 1 / 3, "site-a <10 bin = 1/3 h");
  assert.equal(result.rows.find((r) => r.equipUuid === B.equipUuid).bins[0].hours, 0, "site-b never below 10 degC");
});

// ---- 3. economizer -----------------------------------------------------------------------------------------------------------
test("analyze_economizer: n, n_identifiable, median residual and MAE equal TRUTH per equip", async () => {
  const { result } = await ok({ tool: "analyze_economizer", days: DAYS });
  for (const [S, id] of [[A, "site-a"], [B, "site-b"]]) {
    const rows = result.rows.filter((r) => r.equipUuid === S.equipUuid);
    assert.equal(rows.length, 1);
    const [r] = rows, T = TRUTH[id].economizer;
    assert.equal(r.n, T.n, `${id} n`);
    assert.equal(r.n_identifiable, T.nIdent, `${id} n_identifiable`);
    near(r.median_residual_k, T.medianResidK, `${id} median`);
    near(r.mae_k, T.maeResidK, `${id} MAE`);
    assert.equal(r.has_damper, true);
  }
  const a = result.rows.find((r) => r.equipUuid === A.equipUuid);
  near(a.median_residual_k, 0.5, "median ~0.5 K", 0.05);
  near(a.mae_k, 0.5, "MAE ~0.5 K", 0.05);
});

// ---- 4. fault timeline -------------------------------------------------------------------------------------------------------
test("get_fdd_fault_timeline: CMD-1 confirmed 14:05-15:25 then ok; the null-telemetry gap is unknown, never ok", async () => {
  const { result } = await ok({ tool: "get_fdd_fault_timeline", equipUuid: A.equipUuid, rule: "CMD-1", days: 13, dense: true });   // 13 d = 3744 samples, under the 200 KB cap
  assert.equal(result.source, "timeline");
  assert.equal(result.approximate, false);
  assert.equal(result.equipUuid, A.equipUuid);
  const tz = "America/Chicago", at = (h, m) => result.timeline.find((x) => x.ts === new Date(wall(2026, 11, 6, h, m, tz)).toISOString());
  assert.equal(at(14, 0).state, "ok", "raw fault, not yet confirmed (10 min)");
  assert.equal(at(14, 5).state, "confirmed");
  assert.equal(at(15, 25).state, "confirmed");
  assert.equal(at(15, 30).state, "ok", "cleared: ok although the rolling fault_pct is still above 0");
  const T = TRUTH["site-a"].fault, cleared = new Date(Math.round(T.clearedMs)).toISOString();
  assert.ok(result.timeline.filter((x) => x.ts >= cleared).every((x) => x.state === "ok"), "no confirmed after the clear");
  assert.equal(result.timeline.filter((x) => x.state === "confirmed").length, 17, "14:05 .. 15:25");
  assert.equal(result.summary.confirmed, 17);
  assert.equal(result.summary.first_confirmed, new Date(wall(2026, 11, 6, 14, 5, tz)).toISOString());
  assert.equal(result.summary.last_confirmed, new Date(wall(2026, 11, 6, 15, 25, tz)).toISOString());
  assert.equal(result.summary.last_state, "ok");
  // the fan_status gap (Tue 2026-10-27 10:00-13:00) is unknown: a marker, and no ok inside it
  const g0 = wall(2026, 10, 27, 10, 0, tz), g1 = wall(2026, 10, 27, 13, 0, tz);
  const inGap = result.timeline.filter((x) => Date.parse(x.ts) >= g0 && Date.parse(x.ts) < g1);
  assert.ok(inGap.some((x) => x.state === "unknown"), "unknown marker at the gap");
  assert.ok(inGap.every((x) => x.state === "unknown"), "nothing ok/confirmed inside the gap");
  assert.ok(result.summary.unknown >= 1);
  assert.deepEqual(Object.keys(result.timeline[0]).sort(), ["state", "ts"]);
  assert.ok(result.timeline.every((x) => ["confirmed", "ok", "unknown"].includes(x.state)));

  // default = state changes only (an entry holds until the next one)
  const rle = (await ok({ tool: "get_fdd_fault_timeline", equipUuid: A.equipUuid, rule: "CMD-1", days: DAYS })).result;
  assert.equal(rle.dense, false);
  assert.ok(rle.timeline.length < 20 && rle.timeline.length < result.timeline.length);
  const i = rle.timeline.findIndex((x) => x.state === "confirmed");
  assert.equal(rle.timeline[i].ts, new Date(wall(2026, 11, 6, 14, 5, tz)).toISOString());
  assert.equal(rle.timeline[i + 1].ts, new Date(wall(2026, 11, 6, 15, 30, tz)).toISOString());
  assert.equal(rle.timeline[i + 1].state, "ok");
  assert.ok(rle.timeline.some((x) => x.state === "unknown"));
});

test("get_fdd_fault_timeline: site-b has its own lane (all ok); an ambiguous equipRef is an error listing both; a missing rule has no timeline", async () => {
  const b = (await ok({ tool: "get_fdd_fault_timeline", site: "site-b", equip: "AHU-1", rule: "CMD-1", days: DAYS })).result;
  assert.equal(b.equipUuid, B.equipUuid);
  assert.equal(b.summary.confirmed, 0);
  assert.ok(b.summary.ok > 1000 && b.timeline.every((x) => x.state === "ok"));
  const amb = (await run({ tool: "get_fdd_fault_timeline", equip: "AHU-1", rule: "CMD-1" })).result;
  assert.equal(amb.ok, false);
  assert.equal(amb.candidates.length, 2);
  assert.deepEqual(amb.candidates.map((c) => c.equipUuid).sort(), [A.equipUuid, B.equipUuid].sort());
  const none = (await ok({ tool: "get_fdd_fault_timeline", equipUuid: A.equipUuid, rule: "NOPE-9", days: 1 })).result;
  assert.equal(none.source, "none");
  assert.deepEqual(none.timeline, []);
  assert.equal((await run({ tool: "get_fdd_fault_timeline", equipUuid: A.equipUuid })).result.ok, false, "rule is required");
});

test("get_fdd_fault_timeline without a timeline point falls back to fault_pct and says it is approximate", async () => {
  const http = nfHttp();
  const pct = { uuid: "pct-a", name: "CMD-1 fault_pct", layer: "default", pointType: "POINT", attrs: { dis: "CMD-1", markers: "point,his,fdd,fault", equipRef: "AHU-1", siteRef: "site-a", ruleRef: "CMD-1", equipUuid: A.equipUuid } };
  const post = http.post.bind(http);
  http.post = async (p, body) => {
    const r = await post(p, body);
    if (p !== "/api/v1/point/query" || body.layer === "model") return r;
    const site = body.structuredQuery && body.structuredQuery.field && body.structuredQuery.field.text;
    return { data: { points: [...r.data.points.filter((x) => !/fault_timeline/.test(x.attrs.markers)), ...(site === "site-a" ? [pct] : [])] } };
  };
  const { result } = await ok({ tool: "get_fdd_fault_timeline", equipUuid: A.equipUuid, rule: "CMD-1", days: 1 }, { http });
  assert.equal(result.source, "fault_pct");
  assert.equal(result.approximate, true);
});

// ---- 5. resolve_equipment_roles ------------------------------------------------------------------------------------------------
test("resolve_equipment_roles: bound roles by equipUuid or (siteRef, equipRef); an ambiguous equipRef is an error with candidates", async () => {
  const a = (await ok({ tool: "resolve_equipment_roles", equipUuid: A.equipUuid })).result;
  const b = (await ok({ tool: "resolve_equipment_roles", siteRef: "site-b", equipRef: "AHU-1" })).result;
  assert.equal(a.equipUuid, A.equipUuid);
  assert.equal(b.equipUuid, B.equipUuid);
  assert.ok(a.kinds.includes("ahu"));
  for (const role of ["fan_status", "fan_cmd", "oa_t", "rat", "mat", "oa_damper_pct", "compressor_status"]) {
    assert.deepEqual(a.roles[role].map((p) => p.uuid), [A.points[role].uuid], `site-a ${role}`);
    assert.deepEqual(b.roles[role].map((p) => p.uuid), [B.points[role].uuid], `site-b ${role}`);
  }
  assert.ok(a.roles.fan_status.every((p) => p.siteRef === "site-a") && b.roles.fan_status.every((p) => p.siteRef === "site-b"));
  assert.ok(Array.isArray(a.runnable_rules) && a.runnable_rules.includes("CMD-1"));
  const amb = (await run({ tool: "resolve_equipment_roles", equipRef: "AHU-1" })).result;
  assert.equal(amb.ok, false);
  assert.match(amb.error, /matches 2 equips/);
  assert.deepEqual(amb.candidates.map((c) => c.siteRef).sort(), ["site-a", "site-b"]);
  assert.equal((await run({ tool: "resolve_equipment_roles", site: "site-a", equip: "NOPE" })).result.ok, false);
  assert.equal((await run({ tool: "resolve_equipment_roles", equipUuid: "AHU-1" })).result.ok, false, "equipUuid matches uuids only");
});

// ---- 6. explain_missing_rcx_view --------------------------------------------------------------------------------------------------
test("explain_missing_rcx_view: names the missing role, the kind mismatch, and no-data", async () => {
  const miss = (await ok({ tool: "explain_missing_rcx_view", viewId: "duct_static_ts" })).result;
  assert.equal(miss.available, false);
  assert.ok(miss.missing_roles.includes("duct_static"), "the registry's rcxMissing role");
  assert.equal(miss.view.id, "duct_static_ts");
  assert.equal(miss.equips.length, 2);
  assert.deepEqual(miss.equips.map((e) => e.equipUuid).sort(), [A.equipUuid, B.equipUuid].sort());
  assert.ok(miss.equips.every((e) => e.status === "missing_roles" && e.missing_roles.includes("duct_static")));
  assert.ok(miss.reasons.some((r) => /duct_static/.test(r)));
  const kind = (await ok({ tool: "explain_missing_rcx_view", viewId: "weekly-pump", site: "site-a" })).result;
  assert.equal(kind.available, false);
  assert.equal(kind.equips.length, 1);
  assert.equal(kind.equips[0].status, "kind_mismatch");
  const ready = (await ok({ tool: "explain_missing_rcx_view", viewId: "weekly-fan" })).result;
  assert.equal(ready.available, true);
  assert.ok(ready.equips.every((e) => e.status === "ready"));
  // bound roles but no history in the span (the clock is far past the data)
  const empty = (await ok({ tool: "explain_missing_rcx_view", viewId: "weekly-fan" }, { now: NOW + 3 * 365 * 86400e3 })).result;
  assert.equal(empty.available, false);
  assert.ok(empty.equips.every((e) => e.status === "no_data" && e.no_data_roles.includes("fan_status")));
  const unknown = (await run({ tool: "explain_missing_rcx_view", viewId: "nope" })).result;
  assert.equal(unknown.ok, false);
  assert.ok(unknown.views.includes("weekly-fan"));
});

// ---- 7. read only --------------------------------------------------------------------------------------------------------------------
test("read-only proxy: GET and the read POSTs pass, every write is blocked", async () => {
  const seen = [];
  const raw = {
    defaults: { baseURL: "http://nf.test" },
    get: async (p) => { seen.push(["GET", p]); return { data: {} }; },
    post: async (p) => { seen.push(["POST", p]); return { data: {} }; },
    put: async (p) => { seen.push(["PUT", p]); return {}; },
    patch: async (p) => { seen.push(["PATCH", p]); return {}; },
    delete: async (p) => { seen.push(["DELETE", p]); return {}; },
    request: async (c) => { seen.push(["REQUEST", c]); return {}; },
  };
  const ro = analytics.readOnlyHttp(raw);
  assert.equal(ro.defaults.baseURL, "http://nf.test");
  await ro.get("/api/v1/point/data?uuids=x");
  await ro.get("/api/v1/schedules");
  await ro.post("/api/v1/point/query", { layer: "model" });
  await ro.post("/api/v1/auth/token", {});
  assert.equal(seen.length, 4);
  for (const attempt of [
    () => ro.post("/api/v1/point/points", { points: [] }),         // UpdatePoints (model writes)
    () => ro.post("/api/v1/points/data", { points: [] }),          // AddData
    () => ro.post("/api/v1/schedules", {}),
    () => ro.post("/api/v1/bacnet/writeproperty", {}),
    () => ro.post("/api/v1/point/query/../points", {}),
    () => ro.put("/api/v1/schedules/x", {}),
    () => ro.patch("/api/v1/bacnet/local", {}),
    () => ro.delete("/api/v1/point/points"),
    () => ro.request({ method: "POST", url: "/api/v1/point/points" }),
    () => ro.get("http://evil.test/exfil"),
  ]) await assert.rejects(attempt, /read-only/);
  assert.equal(seen.length, 4, "nothing blocked reached the underlying http");
  assert.throws(() => { ro.post = () => {}; }, TypeError, "the proxy cannot be re-pointed");
});

test("read-only: a tool run never writes, and a write attempt inside the hook's http fails the run instead of going out", async () => {
  const http = nfHttp();
  for (const tool of Object.keys(analytics.TOOLS)) {
    const args = { tool, days: 2, equipUuid: A.equipUuid, rule: "CMD-1", viewId: "weekly-fan" };
    const { result } = await run(args, { http });
    assert.equal(result.ok, true, `${tool}: ${result.error}`);
  }
  assert.deepEqual(http.writes, { points: [], data: [] }, "no UpdatePoints / AddData");
  assert.ok(http.calls.every(([m, p]) => m === "GET" || ["/api/v1/point/query", "/api/v1/auth/token"].includes(p)), "only read routes were called");
  assert.ok(http.calls.some(([m]) => m === "GET") && http.calls.some(([m]) => m === "POST"));
  // the sandboxed dashboard code gets the same proxy: even a direct api() call to a write route is refused
  const sb = analytics.loadSandbox(analytics.readOnlyHttp(nfHttp()), NOW);
  await assert.rejects(() => sb("api")("http://evil.test/exfil"), /read-only/);
});

// ---- 8. hook plumbing -----------------------------------------------------------------------------------------------------------------
test("the hook function takes args from the NF context, logs one JSON line, rejects an unknown tool, and caps big answers", async () => {
  assert.equal(analytics.argsOf({ args: { tool: "x" } }).tool, "x");
  assert.equal(analytics.argsOf({ args: '{"tool":"y"}' }).tool, "y");
  const bad = (await run({ tool: "drop_tables" })).result;
  assert.equal(bad.ok, false);
  assert.match(bad.error, /args.tool must be one of/);
  assert.ok(Object.keys(analytics.TOOLS).every((t) => bad.error.includes(t)));
  assert.equal(Object.keys(analytics.TOOLS).length, 6);
  // a model with many equips: the list is shortened and flagged, the log line stays under the cap
  const many = nfHttp();
  const post = many.post.bind(many);
  many.post = async (p, body) => {
    const r = await post(p, body);
    if (p === "/api/v1/point/query" && body.layer === "model") {
      const extra = Array.from({ length: 1500 }, (_, i) => ({ uuid: `eq-${i}`, name: `AHU-${i}`, layer: "model", pointType: "EQUIPMENT", attrs: { id: `AHU-${i}`, dis: `AHU-${i} ${"x".repeat(60)}`, markers: "equip,ahu", siteRef: "site-a" } }));
      const points = [...r.data.points, ...extra];
      return { data: { points, totalCount: String(points.length) } };
    }
    return r;
  };
  const big = await run({ tool: "explain_missing_rcx_view", viewId: "duct_static_ts", checkData: false }, { http: many });
  assert.equal(big.result.ok, true);
  assert.equal(big.result.truncated, true);
  assert.equal(big.result.equips_total, 1502);
  assert.ok(big.result.equips.length < 1502);
  assert.equal(big.logs.length, 1);
  assert.ok(big.logs[0].length <= 200000);
});
