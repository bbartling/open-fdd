// Runtime engines are DuckDB and Timescale. auto on the DuckDB build is DuckDB.
// sqlite and pglite are refused. A DuckDB package that does not load is an error, and nothing else runs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const fdd = require("../hooks/fdd.js");
const schema = require("../hooks/schema.js");
const eb = require("../hooks/lib/engine-build.js");

const http = { get: async () => ({ data: { resources: [{ memory: { totalBytes: String(16 * 1024 ** 3) } }] } }) };
const fail = () => ({ ok: false, reason: "no native build for this cpu" });
const ok = () => ({ ok: true, reason: "" });

test("engine selection accepts only duckdb and timescale; auto on this build is duckdb", async () => {
  assert.deepEqual(await fdd.pickEngine(http, "auto", undefined, ok), { kind: "duckdb", note: "" });
  assert.deepEqual(await fdd.pickEngine(http, undefined, undefined, ok), { kind: "duckdb", note: "" });
  assert.deepEqual(await fdd.pickEngine(http, "duckdb", undefined, ok), { kind: "duckdb", note: "" });
  assert.deepEqual(await fdd.pickEngine(http, "timescale", { host: "db" }, ok), { kind: "timescale", note: "" });
  assert.deepEqual(await fdd.pickEngine(http, "auto", { host: "db" }, ok), { kind: "timescale", note: "" });
  assert.equal(eb.record().label, "DuckDB backend");
  assert.equal(eb.LABELS.duckdb, "DuckDB backend");
  assert.equal(eb.LABELS.timescale, "Timescale backend");
  assert.equal(eb.resolvedEngineId({}), "duckdb");
  assert.equal(eb.resolvedEngineId({ engine: "duckdb", timescale: { host: "db" } }), "duckdb");
  assert.equal(eb.resolvedEngineId({ engine: "auto", timescale: { host: "db" } }), "timescale");
  assert.equal(eb.resolvedEngineId({ engine: "timescale" }), "timescale");
  assert.equal(eb.resolvedEngineId({ engine: "auto" }, "timescale"), "timescale");
  assert.doesNotMatch(eb.LABELS.duckdb, /2\.0\.1/);
});

test("a Timescale build's auto is timescale and does not load DuckDB", async () => {
  assert.deepEqual(await fdd.pickEngine(http, "auto", undefined, fail, "timescale"), { kind: "timescale", note: "" });
  assert.deepEqual(await fdd.pickEngine(http, "timescale", undefined, fail, "timescale"), { kind: "timescale", note: "" });
});

test("sqlite and pglite fail clearly and name duckdb", async () => {
  for (const name of ["sqlite", "pglite"]) {
    await assert.rejects(() => fdd.pickEngine(http, name, undefined, ok), (e) => {
      assert.match(e.message, new RegExp(`engine "${name}" was removed`));
      assert.match(e.message, /duckdb/);
      assert.equal(e.code, "OPENFDD_ENGINE_RETIRED");
      return true;
    });
  }
  await assert.rejects(() => fdd.pickEngine(http, "mysql", undefined, ok), /unknown engine "mysql"/);
});

test("DuckDB failing to load is reported and does not fall back", async () => {
  await assert.rejects(() => fdd.pickEngine(http, "auto", undefined, fail), (e) => {
    assert.equal(e.message, "DuckDB engine failed to load: no native build for this cpu. Reinstall the DuckDB backend or switch to the Timescale backend.");
    assert.equal(e.code, "OPENFDD_DUCKDB_UNAVAILABLE");
    return true;
  });
  await assert.rejects(
    () => fdd.pickEngine(http, "timescale", { host: "db" }, fail, "duckdb"),
    /DuckDB engine failed to load: no native build/,
  );
  await assert.rejects(() => fdd.pickEngine(http, "duckdb", { host: "db" }, () => false), /module did not load/);

  let created = 0;
  const logs = [];
  const summary = await fdd.runFdd({
    sdk: { http, logEvent: (m) => logs.push(m) },
    config: { engine: "auto" },
    hasDuckdb: fail,
    createEngine: async () => { created += 1; throw new Error("createEngine must not run"); },
  });
  assert.equal(created, 0, "rules are not started");
  assert.equal(summary.ok, false);
  assert.equal(summary.written, 0);
  assert.equal(summary.rules, 0);
  assert.match(summary.error, /DuckDB engine failed to load: no native build for this cpu/);
  assert.match(summary.error, /Reinstall the DuckDB backend or switch to the Timescale backend/);
  assert.ok(!/sqlite|pglite/i.test(summary.error));
  assert.ok(logs.some((m) => m === summary.error));
  await assert.rejects(
    () => fdd({ sdk: { http, logEvent: () => {} }, config: { engine: "duckdb" }, hasDuckdb: fail, createEngine: async () => { created += 1; } }),
    /DuckDB engine failed to load/,
  );
  assert.equal(created, 0);

  const s = await schema.handle({ sdk: { logEvent: () => {} }, config: {}, loadDuckdb: fail });
  assert.equal(s.ok, false);
  assert.equal(s.engine, "duckdb");
  assert.equal(s.engine_label, "DuckDB backend");
  assert.equal(s.engine_build, "DuckDB backend");
  assert.equal(s.engine_library, "@duckdb/node-api");
  assert.equal(s.engine_library_version, "2.0.1-r.1");
  assert.equal(s.engine_error, s.error);
  assert.match(s.engine_error, /DuckDB engine failed to load: no native build for this cpu/);
  assert.doesNotMatch(s.engine_build, /\d/);
});
