// node --test nf-app/tests/schema-probe.test.mjs
// 5.0.13 (#1585): the NF-side read-only schema probe (hooks/schema.js): {ok, installed, required, core_ok} only,
// inside BEGIN TRANSACTION READ ONLY ... ROLLBACK, no connection detail in the answer or the log.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const schema = require("../hooks/schema.js");
const ts = require("../hooks/lib/timescale.js");

/** A pg-client stand-in that records every statement. `version` = the stored schema_version (null = no table). */
function fakeClient(version, failWith, core = true) {
  const sql = [];
  return {
    sql,
    async query(text) {
      sql.push(String(text).trim());
      if (failWith && /to_regclass/.test(text)) throw new Error(failWith);
      if (/AS ok/.test(text)) return { rows: [{ ok: core }] };
      if (/to_regclass/.test(text)) return { rows: [{ r: version === null ? null : "openfdd.config" }] };
      if (/schema_version/.test(text)) return { rows: version === null ? [] : [{ value: version }] };
      return { rows: [] };
    },
  };
}
const sdk = () => { const logs = []; return { logs, logEvent: (m) => logs.push(m) }; };
const cfg = { engine: "timescale", timescale: JSON.stringify({ host: "db.internal", user: "u", password: "s3cret-pw" }) };

test("current schema: ok true with installed, required and core_ok only", async () => {
  const s = sdk(), client = fakeClient(ts.SCHEMA_VERSION);
  const r = await schema.handle({ sdk: s, config: cfg, client });
  assert.deepEqual(r, { ok: true, installed: ts.SCHEMA_VERSION, required: ts.SCHEMA_VERSION, core_ok: true });
  assert.equal(client.sql[0], "BEGIN TRANSACTION READ ONLY");
  assert.equal(client.sql.at(-1), "ROLLBACK");
  assert.ok(client.sql.every((q) => !/^(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)/i.test(q)), "only reads");
});

test("schema behind or absent: ok false, installed is the stored version (0 when absent)", async () => {
  assert.deepEqual(await schema.handle({ sdk: sdk(), config: cfg, client: fakeClient(2) }),
    { ok: false, installed: 2, required: ts.SCHEMA_VERSION, core_ok: false });
  assert.deepEqual(await schema.handle({ sdk: sdk(), config: cfg, client: fakeClient(null) }),
    { ok: false, installed: 0, required: ts.SCHEMA_VERSION, core_ok: false });
});

test("current version but the core tables / input view are missing: not ok, core_ok false", async () => {
  assert.deepEqual(await schema.handle({ sdk: sdk(), config: cfg, client: fakeClient(ts.SCHEMA_VERSION, null, false) }),
    { ok: false, installed: ts.SCHEMA_VERSION, required: ts.SCHEMA_VERSION, core_ok: false });
});

test("Timescale not selected: a clean skip, no connection attempted", async () => {
  const client = fakeClient(3);
  for (const config of [{}, { engine: "sqlite", timescale: cfg.timescale }, { engine: "pglite" }]) {
    const r = await schema.handle({ sdk: sdk(), config, client });
    assert.equal(r.ok, true); assert.equal(r.skipped, true);
  }
  assert.equal(client.sql.length, 0);
});

test("engine timescale without the option fails loudly and names no value", async () => {
  const r = await schema.handle({ sdk: sdk(), config: { engine: "timescale" } });
  assert.equal(r.ok, false); assert.match(r.error, /"timescale" is not set/);
});

test("a database error is redacted in the answer and the log; the transaction is rolled back", async () => {
  const s = sdk();
  const r = await schema.handle({ sdk: s, config: cfg, client: fakeClient(3, "connect ECONNREFUSED db.internal:5432 password s3cret-pw") });
  assert.equal(r.ok, false);
  const all = JSON.stringify(r) + s.logs.join("\n");
  assert.ok(!all.includes("s3cret-pw"), "password never leaves the hook");
  assert.ok(!all.includes("db.internal"), "host never leaves the hook");
  assert.deepEqual(Object.keys(await schema.handle({ sdk: sdk(), config: cfg, client: fakeClient(3) })).sort(), ["core_ok", "installed", "ok", "required"]);
});

test("an unparsable option is reported without echoing it", async () => {
  const r = await schema.handle({ sdk: sdk(), config: { engine: "timescale", timescale: "not json or url s3cret" } });
  assert.equal(r.ok, false); assert.ok(!JSON.stringify(r).includes("s3cret"));
});

test("a postgres:// option: host, user and database from the URL are redacted from a driver error", async () => {
  const s = sdk();
  const config = { engine: "timescale", timescale: "postgres://fdduser:s3cret-pw@db.internal:5432/fdddb" };
  const r = await schema.handle({ sdk: s, config, client: fakeClient(3, "getaddrinfo ENOTFOUND db.internal for fdduser on fdddb") });
  assert.equal(r.ok, false);
  const all = JSON.stringify(r) + s.logs.join("\n");
  for (const v of ["db.internal", "fdduser", "fdddb", "s3cret-pw"]) assert.ok(!all.includes(v), `${v} never leaves the hook`);
});
