// node --test nf-app/tests/nf-client.test.mjs — api() retry policy in static/nf.js and lite/static/nf.js.
// A lost or transient-error response to a non-idempotent call (StartHook!) must never be re-sent.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const editions = {
  app: new URL("../static/nf.js", import.meta.url),
  lite: new URL("../../lite/static/nf.js", import.meta.url),
};

/** Load nf.js with a scripted fake fetch: `statuses` is the status sequence returned per call. */
function load(file, statuses) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body });
    const status = statuses[Math.min(calls.length - 1, statuses.length - 1)];
    return { ok: status >= 200 && status < 300, status, json: async () => ({ ok: true, n: calls.length }) };
  };
  const ctx = vm.createContext({
    fetch, console, URLSearchParams, TextDecoder, atob, btoa,
    setTimeout: (fn) => { fn(); return 0; },          // no real back-off delays in tests
  });
  vm.runInContext(readFileSync(new URL("paging.js", file), "utf8"), ctx, { filename: "paging.js" });   // nf.js needs OfddPaging
  vm.runInContext(readFileSync(file, "utf8"), ctx, { filename: "nf.js" });
  return { api: vm.runInContext("api", ctx), calls };
}

for (const [ed, file] of Object.entries(editions)) {
  test(`[${ed}] GET retries transient 403/429/502/503/504 and then succeeds`, async () => {
    for (const st of [403, 429, 502, 503, 504]) {
      const { api, calls } = load(file, [st, st, 200]);
      const r = await api("/api/v1/bacnet/local");
      assert.equal(r.ok, true);
      assert.equal(calls.length, 3, `status ${st}`);
      assert.ok(calls.every((c) => c.method === "GET"));
    }
  });

  test(`[${ed}] GET gives up after 4 attempts`, async () => {
    const { api, calls } = load(file, [503]);
    await assert.rejects(api("/api/v1/bacnet/local?x=1"), /\/api\/v1\/bacnet\/local → HTTP 503/);
    assert.equal(calls.length, 4);
  });

  test(`[${ed}] idempotent POSTs (point/query, auth/token) are retried`, async () => {
    for (const path of ["/api/v1/point/query", "/api/v1/auth/token"]) {
      const { api, calls } = load(file, [503, 403, 200]);
      await api(path, { pageSize: 5 });
      assert.equal(calls.length, 3, path);
      assert.ok(calls.every((c) => c.method === "POST"));
    }
  });

  test(`[${ed}] StartHook and other POSTs are sent exactly once, whatever the status`, async () => {
    for (const st of [403, 429, 502, 503, 504]) {
      const { api, calls } = load(file, [st, 200]);
      await assert.rejects(api("/api/v1/apps/open-fdd/hooks/fdd", {}), new RegExp(`HTTP ${st}`));
      assert.equal(calls.length, 1, `StartHook with ${st} was re-sent`);
      assert.equal(calls[0].method, "POST");
    }
    const { api, calls } = load(file, [504, 200]);
    await assert.rejects(api("/api/v1/point/points", { points: [] }), /HTTP 504/);
    assert.equal(calls.length, 1);
  });

  test(`[${ed}] PATCH and DELETE are never retried`, async () => {
    for (const method of ["PATCH", "DELETE"]) {
      const { api, calls } = load(file, [503, 200]);
      await assert.rejects(api("/api/v1/bacnet/local/OBJECT_ANALOG_VALUE/1", method === "PATCH" ? { a: 1 } : undefined, { method }), /HTTP 503/);
      assert.equal(calls.length, 1, method);
      assert.equal(calls[0].method, method);
    }
  });

  test(`[${ed}] clerk-js is pinned to an exact version`, () => {
    const src = readFileSync(file, "utf8");
    const m = src.match(/CLERK_JS_VERSION = "(\d+\.\d+\.\d+)"/);
    assert.ok(m, "exact semver constant");
    assert.ok(src.includes("clerk-js@${CLERK_JS_VERSION}/"));
    assert.ok(!/clerk-js@5\//.test(src), "no moving major");
  });
}
