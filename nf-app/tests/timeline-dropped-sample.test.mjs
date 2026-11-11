// node --test nf-app/tests/timeline-dropped-sample.test.mjs
// 5.0.13 (#1574): NF AddData answers a batch-level {"success": true} even when it silently drops a sample (older than the
// point's retention, or an unsupported value); the reply has no per-sample status. Does a normal Open-FDD timeline batch
// ever lose a retry because fddTimelineThrough advanced past a dropped sample?
//
// The mock below drops samples older than `retentionMs` and still answers success:true, stores only what it kept, and
// the hook is run twice (the second run sees the first run's model records, like NF would serve them).
//
// Evidence / verdict (asserted below):
//   1. Every value the hook submits is 0 or 1 (finite), so an "unsupported value" drop cannot happen.
//   2. Every timestamp it submits lies inside its own trailing windowHours window. With windowHours <= the point's
//      retention (the supported configuration: the default is 24 h) NOTHING is dropped, so nothing needs a retry.
//   3. Only a window longer than the retention (unsupported: windowHours > retention) drops samples, and then the
//      watermark does move past them: they are not retried. That is the documented limit, pinned here so a change to
//      it is deliberate. No logic change is needed for a supported run.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { twoSite as fx, TRUTH, fakeSdkHttp } from "./fixtures/two_site.mjs";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
const NOW = Math.round(TRUTH["site-a"].fault.nowMs);
const H = 3600e3;

/** fake NF with a retention: AddData keeps only samples newer than now - retentionMs, but always says success:true. */
function retentionNf(nowMs, retentionMs, priorModels) {
  const base = fakeSdkHttp(fx, { nowMs });
  const submitted = new Map(), stored = new Map(), models = new Map();
  return {
    submitted, stored, models,
    async post(p, body) {
      if (p === "/api/v1/points/data") {
        for (const x of body.points) {
          submitted.set(x.uuid, [...(submitted.get(x.uuid) || []), ...x.values.map((v) => [Date.parse(v.ts), v.real])]);
          const kept = x.values.filter((v) => Date.parse(v.ts) >= nowMs - retentionMs).map((v) => [Date.parse(v.ts), v.real]);
          stored.set(x.uuid, [...(stored.get(x.uuid) || []), ...kept]);
        }
        return { data: { success: true } };                       // batch level only: no per-sample status
      }
      if (p === "/api/v1/point/points") for (const r of body.points) if (r.layer === "model") models.set(r.uuid, r);
      const r = await base.post(p, body);
      if (p === "/api/v1/point/query" && body.layer === "model") return { data: { points: [...r.data.points, ...priorModels.values()] } };
      return r;
    },
    get: (p) => base.get(p),
  };
}
async function runAt(nowMs, retentionMs, prior, windowHours) {
  const http = retentionNf(nowMs, retentionMs, prior), logs = [];
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: { engine: "sqlite", windowHours }, now: nowMs });
  assert.equal(summary.errors, 0, logs.join("\n"));
  return { http, summary };
}
const timelineUuids = (http) => [...http.models.values()].filter((r) => /fault_timeline/.test(r.attrs.markers)).map((r) => r.uuid);

test("supported config (window <= retention): every submitted sample is kept, none is lost, the next run continues cleanly", async () => {
  const r1 = await runAt(NOW, 48 * H, new Map(), 24);
  const uuids = timelineUuids(r1.http);
  assert.ok(uuids.length >= 40, "timeline points were written");
  for (const u of uuids) {
    const sent = r1.http.submitted.get(u) || [];
    assert.deepEqual(r1.http.stored.get(u) || [], sent, "a retention at least as long as the window drops nothing");
    for (const [ts, v] of sent) {
      assert.ok(v === 0 || v === 1, `finite 0/1 value, got ${v}`);
      assert.ok(ts >= NOW - 24 * H && ts <= NOW, "every sample is inside the run's trailing window");
    }
  }
  const r2 = await runAt(NOW + H, 48 * H, r1.http.models, 24);
  for (const u of uuids) {
    const last1 = (r1.http.submitted.get(u) || []).at(-1)?.[0];
    if (last1 == null) continue;
    assert.ok((r2.http.submitted.get(u) || []).every(([ts]) => ts > last1), "second run writes only after the watermark");
    assert.deepEqual(r2.http.stored.get(u) || [], r2.http.submitted.get(u) || [], "and none of those is dropped either");
  }
});

test("unsupported config (window > retention): samples dropped under success:true are NOT retried; the limit is pinned", async () => {
  const r1 = await runAt(NOW, 6 * H, new Map(), 24);
  const uuids = timelineUuids(r1.http).filter((u) => (r1.http.submitted.get(u) || []).length > 100);
  assert.ok(uuids.length > 0);
  const u = uuids[0];
  const sent = r1.http.submitted.get(u), kept = r1.http.stored.get(u);
  assert.ok(kept.length < sent.length, "the mock really dropped out-of-retention samples while answering success:true");
  const last1 = sent.at(-1)[0];
  const r2 = await runAt(NOW + H, 6 * H, r1.http.models, 24);
  assert.ok((r2.http.submitted.get(u) || []).every(([ts]) => ts > last1), "the watermark moved past the dropped samples");
  const lost = sent.filter(([ts]) => !kept.some(([t2]) => t2 === ts) && !(r2.http.submitted.get(u) || []).some(([t2]) => t2 === ts));
  assert.ok(lost.length > 0, "those samples are never resubmitted: windowHours must not exceed the point retention");
});
