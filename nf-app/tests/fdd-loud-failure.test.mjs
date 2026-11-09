// #1550: the fdd hook must not report success while writing nothing; the history hook must tell "no rows" from "failed".
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
const history = require("../hooks/history.js");
const tsLib = require("../hooks/lib/timescale.js");

const STEP = 300;
const NOW = Date.parse("2026-11-09T15:02:00Z");
const NEWEST = Date.parse("2026-11-08T19:00:00Z");
const MODEL = [
  { uuid: "s", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site" } },
  { uuid: "e", name: "AHU-1", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" } },
];
const pt = (uuid, name, markers, extra = {}) => ({
  uuid, name, layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", markers: ["point", "his", ...markers].join(","), dis: name, equipRef: "AHU-1", ...extra },
});
const FANC = (extra = {}) => pt("u-FANC", "FAN-C", ["discharge", "fan", "run", "cmd"], { class: "discharge-run-cmd", unit: "%", ...extra });
const FANS = (extra = {}) => pt("u-FANS", "FAN-S", ["discharge", "fan", "run", "sensor"], { class: "discharge-run-status", ...extra });
const OAT = pt("u-OAT", "OAT", ["outside", "air", "temp", "sensor"], { class: "outside-air-temp-sensor", unit: "°F" });

const F_COLS = ["equipment_id", "fault_hours", "covered_hours", "fault_pct"];
const PACK = {
  poll_seconds: STEP,
  contract: { history: [{ name: "equipment_id", type: "text" }, { name: "timestamp_utc", type: "timestamp" },
    { name: "fan_cmd", type: "double" }, { name: "fan_status", type: "double" }, { name: "oa_t", type: "double" }] },
  rules: {
    "CMD-1": { sql: "-", output_columns: F_COLS },
    "FAN-RUNTIME-HOURS": { sql: "-", output_columns: ["equipment_id", "fan_runtime_hours", "total_hours"] },
  },
};
const resultRec = (ruleId) => ({
  uuid: hook.resultUuid(hook.resultKey(MODEL[1], "site-a", "AHU-1"), ruleId), name: `site-a/AHU-1/${ruleId}`, layer: "model",
  attrs: { dis: `AHU-1 ${ruleId}`, markers: "point,his,fault,fdd", kind: "Number", unit: "%", siteRef: "site-a", equipRef: "AHU-1", ruleRef: ruleId, fddStatus: "ok" },
});
const PRIOR = [resultRec("CMD-1"), resultRec("FAN-RUNTIME-HOURS")];

/** Fake NF: model + default-layer queries, resampled history (empty when noHistory), records writes. */
function fakeHttp({ points, model = [...MODEL, ...PRIOR], noHistory = false } = {}) {
  const writes = { points: [], data: [] };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? model : points } };
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/points/data") { writes.data.push(...body.points); return { data: { success: true } }; }
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (!p.startsWith("/api/v1/point/data?")) throw new Error("unexpected GET " + p);
      const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
      const series = (uuid) => {
        const values = [];
        if (!noHistory) for (let t = NOW - 24 * 3600e3; t < NOW; t += STEP * 1e3) values.push({ ts: new Date(t).toISOString(), double: 1 });
        return { uuid, values };
      };
      return { data: { data: uuids.map(series) } };
    },
  };
}

/** Engine stub. `rows` = what load() returns (timescale: a count); newest = what newestSample() answers. */
const engine = ({ kind = "sqlite", rows, newest = NEWEST } = {}) => async () => ({
  kind,
  async load() { return rows; },
  ...(kind === "timescale" ? { async newestSample() { return newest; } } : {}),
  async query(id) {
    return id === "CMD-1" ? [{ equipment_id: "AHU-1", fault_hours: 0, covered_hours: 24, fault_pct: 0 }]
      : [{ equipment_id: "AHU-1", fan_runtime_hours: 24, total_hours: 24 }];
  },
  async close() {},
});

const run = (http, createEngine, config = {}) => {
  const logs = [];
  const sdk = { http, logEvent: (m) => logs.push(m) };
  return { logs, summary: hook.runFdd({ sdk, config, pack: PACK, createEngine, now: NOW }), hook: () => hook({ sdk, config, pack: PACK, createEngine, now: NOW }) };
};
const staleReasons = (http) => [...new Set(http.writes.points.filter((r) => r.layer === "model" && r.attrs.fddStatus === "stale").map((r) => r.attrs.fddReason))];

test("normal run stays ok: results written, no failure, report in the log", async () => {
  const http = fakeHttp({ points: [FANC(), FANS(), OAT] });
  const r = run(http, engine({ rows: 288 }));
  const s = await r.summary;
  assert.equal(s.failure, null);
  assert.equal(s.eligible, 1);
  assert.equal(s.skipped.length, 0);
  assert.deepEqual(s.status, { ok: 2, fault: 0, "not-assessed": 0, stale: 0 });
  assert.equal(s.source_freshness.newest_sample, "2026-11-09T14:55:00.000Z", "newest bucket the engine saw");
  const out = await run(fakeHttp({ points: [FANC(), FANS(), OAT] }), engine({ rows: 288 })).hook();
  assert.equal(out.failure, null, "the hook returns the summary, it does not throw");
  assert.ok(r.logs.some((l) => /^open-fdd run: engine sqlite, data window .* \(24 h\); newest input sample in the sqlite source \d{4}-/.test(l)), r.logs.join("\n"));
  assert.ok(r.logs.some((l) => /open-fdd counts: eligible 1, evaluated 1, written 2, skipped 0, stale 0/.test(l)));
});

test("empty timescale history: stale 'no input data in window (newest sample at X)', ok:false (throws), freshness reported", async () => {
  const http = fakeHttp({ points: [FANC(), FANS(), OAT] });
  const config = { engine: "timescale", timescale: { host: "db" } };
  const r = run(http, engine({ kind: "timescale", rows: 0 }), config);
  const s = await r.summary;
  assert.equal(s.engine, "timescale");
  assert.equal(s.status.stale, 2);
  assert.deepEqual(staleReasons(http), [`no input data in window (newest sample at ${new Date(NEWEST).toISOString()})`]);
  assert.equal(s.skipped[0].kind, "no-data");
  assert.match(s.failure, /no fresh results were written for any of 1 eligible equips/);
  assert.equal(s.source_freshness.newest_sample, new Date(NEWEST).toISOString());
  assert.equal(s.source_freshness.age_minutes, Math.round((NOW - NEWEST) / 60e3));
  assert.equal(http.writes.data.length, 0, "nothing was written as a value");
  await assert.rejects(run(fakeHttp({ points: [FANC(), FANS(), OAT] }), engine({ kind: "timescale", rows: 0 }), config).hook(),
    (e) => /no fresh results/.test(e.message) && /no input data in window/.test(`${e.message} ${e.summary.skipped[0].detail}`)
      && /eligible 1, evaluated 0, written 0, skipped 1 \(no-data x1\)/.test(e.message)
      && /engine timescale, window 2026-11-08T15:00:00\.000Z \.\. 2026-11-09T15:00:00\.000Z/.test(e.message)
      && /newest input sample 2026-11-08T19:00:00\.000Z/.test(e.message));
  assert.ok(r.logs.some((l) => /open-fdd FAILED/.test(l)));
  assert.ok(r.logs.some((l) => /skipped by reason: no-data x1; stale by reason: no input data in window x2/.test(l)), r.logs.join("\n"));
});

test("sqlite engine, source without data in the window: same reason, newest sample from NF's latest value", async () => {
  const latest = { ts: "2026-11-08T18:55:00Z", double: 1 };
  const http = fakeHttp({ points: [FANC({}), FANS(), OAT].map((p) => ({ ...p, latestValue: latest })), noHistory: true });
  const s = await run(http, engine({ rows: 0 })).summary;
  assert.deepEqual(staleReasons(http), ["no input data in window (newest sample at 2026-11-08T18:55:00.000Z)"]);
  assert.match(s.failure, /eligible equips/);
});

test("missing roles: stale 'required roles missing', ok:false", async () => {
  const http = fakeHttp({ points: [OAT] });   // no fan points: no rule is runnable any more
  const r = run(http, engine({ rows: 288 }));
  const s = await r.summary;
  assert.equal(s.status.stale, 2);
  assert.ok(staleReasons(http).length >= 1 && staleReasons(http).every((x) => /^required roles missing/.test(x)), staleReasons(http).join("|"));
  assert.equal(s.skipped[0].kind, "roles-missing");
  assert.match(s.failure, /no fresh results/);
  assert.deepEqual(s.stale_reasons, { "required roles missing": 2 });
  await assert.rejects(run(fakeHttp({ points: [OAT] }), engine({ rows: 288 })).hook(), /roles-missing x1/);
});

test("unusable units: stale 'unit unusable' naming the role, ok:false", async () => {
  // fan_cmd (a 0-1 fraction) with no unit cannot be told from 0-100; fan_status with a temperature unit is not a 0/1 status
  const http = fakeHttp({ points: [FANC({ unit: "" }), FANS({ unit: "°F" }), OAT] });
  const r = run(http, engine({ rows: 288 }));
  const s = await r.summary;
  assert.equal(s.status.stale, 2);
  assert.ok(staleReasons(http).every((x) => /^unit unusable \(role (fan_cmd|fan_status)/.test(x)), staleReasons(http).join("|"));
  assert.equal(s.skipped[0].kind, "unit-unusable");
  assert.match(s.failure, /no fresh results/);
  assert.deepEqual(s.stale_reasons, { "unit unusable": 2 });
  await assert.rejects(run(fakeHttp({ points: [FANC({ unit: "" }), FANS({ unit: "°F" }), OAT] }), engine({ rows: 288 })).hook(), /unit-unusable x1/);
});

test("not a failure: dry run, nothing eligible, or at least one equip freshly assessed", async () => {
  // dry run writes nothing by design
  const dry = await run(fakeHttp({ points: [OAT] }), engine({ rows: 288 }), { dryRun: true }).summary;
  assert.equal(dry.failure, null);
  // an equip with no rules that apply and no results published before is not eligible: nothing to be loud about
  const none = await run(fakeHttp({ points: [OAT], model: MODEL }), engine({ rows: 288 })).summary;
  assert.equal(none.eligible, 0);
  assert.equal(none.failure, null);
  // one healthy equip among broken ones keeps the run ok (the broken one is still reported)
  const model2 = [...MODEL, { uuid: "e2", name: "AHU-2", pointType: "EQUIPMENT", attrs: { id: "AHU-2", siteRef: "site-a", markers: "equip,ahu" } }];
  const ahu2 = [FANC(), FANS(), OAT].map((p) => ({ ...p, uuid: p.uuid + "-2", attrs: { ...p.attrs, equipRef: "AHU-2" } }));
  const mixed = await run(fakeHttp({ points: [...ahu2, OAT], model: [...model2, ...PRIOR] }), engine({ rows: 288 })).summary;
  assert.equal(mixed.failure, null);
  assert.equal(mixed.skipped.length, 1);
  assert.equal(mixed.skipped[0].equip, "AHU-1");
});

test("history hook: empty result is ok with a reason and the newest source timestamp; failures are ok:false", async () => {
  const realConnect = tsLib.connect;
  const sdk = { logEvent() {} };
  const args = { uuids: ["u-1"], from: "2026-11-01T00:00:00Z", to: "2026-11-02T00:00:00Z" };
  const client = (onHistory) => ({
    async query(sql) {
      if (/history_buckets/.test(sql)) return onHistory();
      if (/max\(ts\)/.test(sql)) return { rows: [{ t: new Date(NEWEST) }] };
      return { rows: [] };
    },
    async end() {},
  });
  try {
    tsLib.connect = async () => client(() => ({ rows: [] }));
    const empty = await history.handle({ sdk, args, config: { timescale: { host: "db" } } });
    assert.equal(empty.ok, true);
    assert.equal(empty.row_count, 0);
    assert.deepEqual(empty.rows, []);
    assert.equal(empty.reason, "no rows in the requested range");
    assert.equal(empty.newest_source_ts, new Date(NEWEST).toISOString());

    tsLib.connect = async () => client(() => { throw Object.assign(new Error('relation "openfdd.nf_samples" does not exist'), { code: "42P01" }); });
    const bad = await history.handle({ sdk, args, config: { timescale: { host: "db" } } });
    assert.equal(bad.ok, false);
    assert.equal(bad.stage, "query");
    assert.match(bad.error, /nf_samples/);
    assert.equal(bad.error_code, "42P01");

    tsLib.connect = async () => { throw Object.assign(new Error("connect ECONNREFUSED"), { code: "ECONNREFUSED" }); };
    const down = await history.handle({ sdk, args, config: { timescale: { host: "db" } } });
    assert.equal(down.ok, false);
    assert.equal(down.stage, "connect");

    // a bad request is still an error, not a database failure
    tsLib.connect = async () => client(() => ({ rows: [] }));
    await assert.rejects(history.handle({ sdk, args: { from: "x" }, config: { timescale: { host: "db" } } }), /uuids/);
  } finally {
    tsLib.connect = realConnect;
  }
});
