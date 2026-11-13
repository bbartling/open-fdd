// No database needed: historyRoute bounds (checked BEFORE any query), the SQL shape (transaction, statement_timeout,
// LIMIT, bound parameters), explicit engine selection, and percent handling helpers.
//   node --test nf-app/timescale/test/bounds.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("../../hooks/lib/timescale.js");
const { createEngine } = require("../../hooks/lib/engines.js");
const history = require("../../hooks/history.js");
const pack = JSON.parse(readFileSync(new URL("../../rules/pack-postgres.json", import.meta.url), "utf8"));

const U1 = "11111111-1111-1111-1111-111111111111";
const U2 = "22222222-2222-2222-2222-222222222222";
const uuids = (n) => Array.from({ length: n }, (_, i) => `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`);

/** Fake pg client: records every query; `rows` answers the history SELECT; `fail` throws on it. */
function fake({ rows = [], fail = null } = {}) {
  const queries = [];
  return {
    queries,
    async query(sql, params) {
      queries.push({ sql: String(sql), params });
      if (/history_buckets/.test(sql)) {
        if (fail) throw fail;
        return { rows, rowCount: rows.length };
      }
      return { rows: [], rowCount: 0 };
    },
  };
}
const row = (u, i, n = 5) => ({ point_uuid: u, bucket: new Date(Date.UTC(2026, 9, 1, 0, i)), avg: 1, min: 0, max: 2, n });
const good = { uuids: [U1], from: "2026-10-01T00:00:00Z", to: "2026-10-02T00:00:00Z", bucket: "1 hour" };

test("a huge span with a 1-second bucket is rejected before any query", async () => {
  for (const bucket of ["1 second", "30 seconds", "59 seconds"]) {
    const c = fake();
    await assert.rejects(ts.historyRoute(c, { uuids: [U1], from: "2000-01-01T00:00:00Z", to: "2026-01-01T00:00:00Z", bucket }), /at least 60 seconds|longer than/);
    assert.equal(c.queries.length, 0, bucket);
  }
  const c = fake();
  await assert.rejects(ts.historyRoute(c, { uuids: [U1], from: "2026-10-01T00:00:00Z", to: "2026-10-02T00:00:00Z", bucket: "1 second" }), /at least 60 seconds/);
  assert.equal(c.queries.length, 0);
});

test("a span beyond maxSpanDays is rejected", async () => {
  const c = fake();
  await assert.rejects(ts.historyRoute(c, { uuids: [U1], from: "1990-01-01T00:00:00Z", to: "2026-01-01T00:00:00Z", bucket: "1 day" }), /longer than 3660 days/);
  await assert.rejects(ts.historyRoute(c, good, { maxSpanDays: 0.5 }), /longer than 0.5 days/);
  assert.equal(c.queries.length, 0);
});

test("zero / malformed buckets are rejected", async () => {
  for (const bucket of ["0 minutes", "0 hours", "0 seconds", "-5 minutes", "1.5 hours", "1 day; drop table x", "hour", "5 fortnights", "9999999 days"]) {
    const c = fake();
    await assert.rejects(ts.historyRoute(c, { ...good, bucket }), /args.bucket/, bucket);
    assert.equal(c.queries.length, 0, bucket);
  }
});

test("malformed times are rejected", async () => {
  const bad = ["garbage", "", "   ", null, undefined, NaN, Infinity, -Infinity, -5, 0, {}, [], true, "2026-13-45T00:00:00Z", 1e20];
  for (const v of bad) {
    for (const key of ["from", "to"]) {
      const c = fake();
      await assert.rejects(ts.historyRoute(c, { ...good, [key]: v }), /args\.(from|to)/, `${key}=${String(v)}`);
      assert.equal(c.queries.length, 0);
    }
  }
  const c = fake();
  await assert.rejects(ts.historyRoute(c, { ...good, from: good.to }), /from must be before/);
  await assert.rejects(ts.historyRoute(c, { ...good, from: "2026-10-03T00:00:00Z" }), /from must be before/);
  assert.equal(c.queries.length, 0);
  // epoch ms numbers are fine
  const ok = fake();
  const r = await ts.historyRoute(ok, { ...good, from: Date.parse(good.from), to: Date.parse(good.to) });
  assert.equal(r.from, "2026-10-01T00:00:00.000Z");
});

test("bad uuid lists are rejected", async () => {
  for (const u of [undefined, [], "x", [""], [1], [null], [uuids(1)[0], "x".repeat(200)]]) {
    const c = fake();
    await assert.rejects(ts.historyRoute(c, { ...good, uuids: u }), /uuids/);
    assert.equal(c.queries.length, 0);
  }
  await assert.rejects(ts.historyRoute(fake(), { ...good, uuids: uuids(201) }), /at most 200 uuids/);
});

test("too many points: coarsened with an explicit flag (or rejected)", async () => {
  const c = fake();
  const args = { uuids: uuids(100), from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z", bucket: "1 minute" };
  const r = await ts.historyRoute(c, args);
  assert.equal(r.coarsened, true);
  assert.equal(r.requested_bucket, "1 minute");
  assert.notEqual(r.bucket, "1 minute");
  const secs = { "5 minutes": 300, "15 minutes": 900, "1 hour": 3600, "6 hours": 21600, "1 day": 86400, "1 week": 604800, "1 month": 2592000 }[r.bucket];
  assert.ok(secs, `bucket ${r.bucket}`);
  assert.ok((Math.floor(59 * 86400 / secs) + 2) * 100 <= r.max_points, "estimated points within max_points");
  assert.equal(c.queries.find((q) => /history_buckets/.test(q.sql)).params[3], r.bucket, "the coarsened bucket is what runs");
  // the request cannot raise the server limit
  const sneaky = await ts.historyRoute(fake(), { ...args, maxPoints: 1e9, statementTimeoutMs: 1e9 });
  assert.equal(sneaky.max_points, 200000);
  assert.equal(sneaky.coarsened, true);
  // coarsen: false -> reject; nothing fits -> reject; auto bucket with many uuids is also bounded
  const n = fake();
  await assert.rejects(ts.historyRoute(n, { ...args, coarsen: false }), /would return about/);
  await assert.rejects(ts.historyRoute(n, args, { maxPoints: 100 }), /even with the coarsest bucket/);
  assert.equal(n.queries.length, 0);
  const auto = await ts.historyRoute(fake(), { uuids: uuids(200), from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z" });
  assert.ok((Math.floor(59 * 86400 / ({ "6 hours": 21600, "1 day": 86400 }[auto.bucket])) + 2) * 200 <= 200000);
});

test("query shape: transaction, SET LOCAL statement_timeout, LIMIT max_points + 1, bound parameters", async () => {
  const c = fake({ rows: [row(U1, 0)] });
  const r = await ts.historyRoute(c, good);
  const sql = c.queries.map((q) => q.sql);
  assert.equal(sql[0], "BEGIN");
  assert.match(sql[1], /set_config\('statement_timeout', \$1::text, true\)/);
  assert.deepEqual(c.queries[1].params, ["20000ms"]);
  assert.match(sql[2], /LIMIT \$5::int/);
  assert.deepEqual(c.queries[2].params, [[U1], "2026-10-01T00:00:00.000Z", "2026-10-02T00:00:00.000Z", "1 hours", 200001]);
  assert.equal(sql[3], "COMMIT");
  assert.ok(!/U1|1111/.test(sql[2]), "values are bound, not interpolated");
  assert.equal(r.max_points, 200000);
  assert.equal(r.coverage.with_data, 1);
  assert.equal(r.coverage.points[U1].samples, 5);
  // configured limits
  const c2 = fake();
  await ts.historyRoute(c2, good, { statementTimeoutMs: 7500, maxPoints: 5000 });
  assert.deepEqual(c2.queries[1].params, ["7500ms"]);
  assert.equal(c2.queries[2].params[4], 5001);
});

test("truncation is detected by the SQL LIMIT and by the byte cap", async () => {
  const many = Array.from({ length: 4 }, (_, i) => row(U1, i));
  const r = await ts.historyRoute(fake({ rows: many }), good, { maxPoints: 3 });
  assert.equal(r.truncated, true);
  assert.equal(r.rows.length, 3);
  assert.equal(r.coverage.complete, false);
  const full = await ts.historyRoute(fake({ rows: many.slice(0, 3) }), good, { maxPoints: 3 });
  assert.equal(full.truncated, false);
  const bytes = await ts.historyRoute(fake({ rows: many }), good, { maxBytes: 500 });
  assert.equal(bytes.truncated, true);
  assert.ok(bytes.rows.length < 4);
});

test("unknown uuids: empty rows and explicit coverage", async () => {
  const r = await ts.historyRoute(fake({ rows: [row(U1, 0)] }), { ...good, uuids: [U1, U2] });
  assert.deepEqual(r.coverage.without_data, [U2]);
  assert.equal(r.coverage.with_data, 1);
  const none = await ts.historyRoute(fake({ rows: [] }), { ...good, uuids: [U1, U2] });
  assert.deepEqual(none.rows, []);
  assert.deepEqual(none.coverage.without_data, [U1, U2]);
  assert.equal(none.truncated, false);
});

test("statement timeout: rolled back and reported", async () => {
  const err = Object.assign(new Error("canceling statement due to statement timeout"), { code: "57014" });
  const c = fake({ fail: err });
  await assert.rejects(ts.historyRoute(c, good), (e) => e.code === "history_timeout" && /exceeded 20000 ms/.test(e.message));
  assert.equal(c.queries.at(-1).sql, "ROLLBACK");
  const other = fake({ fail: Object.assign(new Error("boom"), { code: "XX000" }) });
  await assert.rejects(ts.historyRoute(other, good), /boom/);
  assert.equal(other.queries.at(-1).sql, "ROLLBACK");
});

test("history hook passes config.history limits and still needs config.timescale", async () => {
  await assert.rejects(history.handle({ sdk: {}, args: good, config: {} }), /Timescale connection settings not found/);
});

test("engine timescale without config.timescale fails visibly (no silent fallback)", async () => {
  await assert.rejects(createEngine({ kind: "timescale", pack }), /Timescale connection settings not found/);
  await assert.rejects(createEngine({ kind: "timescale", pack, config: {} }), /Timescale connection settings not found/);
  await assert.rejects(createEngine({ kind: "timescale", pack, config: { database: "x" } }), /Timescale connection settings not found/);
  assert.throws(() => ts.requireConfig(undefined), /Timescale connection settings not found/);
  assert.equal(ts.requireConfig({ host: "h" }).host, "h");
  assert.ok(ts.requireConfig({ connectionString: "postgres://x" }));
});

test("optional pgweb sidecar stays off by default, private, TLS + basic_auth, read-only", () => {
  const baseCompose = readFileSync(new URL("../../../deploy/nf-caddy/docker-compose.yml", import.meta.url), "utf8");
  const pgCompose = readFileSync(new URL("../../../deploy/nf-caddy/docker-compose.pgweb.yml", import.meta.url), "utf8");
  const pgCaddy = readFileSync(new URL("../../../deploy/nf-caddy/pgweb.caddy", import.meta.url), "utf8");
  const pgTls = readFileSync(new URL("../../../deploy/nf-caddy/Caddyfile.tls.pgweb", import.meta.url), "utf8");
  const pgGrants = readFileSync(new URL("../../../deploy/nf-caddy/pgweb-grants.sql", import.meta.url), "utf8");
  const routes = readFileSync(new URL("../../../deploy/nf-caddy/routes.caddy", import.meta.url), "utf8");

  assert.doesNotMatch(baseCompose, /pgweb/, "default compose does not run pgweb");
  assert.doesNotMatch(routes, /pgweb/, "default routes do not expose pgweb");
  assert.match(pgCompose, /profiles:\s*\["pgweb"\]/);
  assert.match(pgCompose, /--readonly/);
  assert.match(pgCompose, /--lock-session/);
  assert.match(pgCompose, /PGWEB_DATABASE_URL=/);
  // pgweb service must not publish any host port
  const pgBlock = pgCompose.split(/^  pgweb:/m)[1] || "";
  assert.doesNotMatch(pgBlock, /^\s+ports:/m, "pgweb must not publish a host port");
  assert.match(pgCaddy, /@pgweb path \/pgweb \/pgweb\/\*/);
  assert.match(pgCaddy, /basic_auth/);
  assert.match(pgTls, /tls \/certs\/server\.crt \/certs\/server\.key/);
  assert.match(pgTls, /import \/etc\/caddy\/pgweb\.caddy/);
  assert.match(pgGrants, /default_transaction_read_only = on/);
  assert.match(pgGrants, /statement_timeout = '10s'/);
  assert.doesNotMatch(pgGrants, /(INSERT|UPDATE|DELETE|TRUNCATE|ALTER TABLE|CREATE TABLE)/i);
});
