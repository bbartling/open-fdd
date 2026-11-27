// node --test nf-app/tests/engine-select.test.mjs
// How the NF plugin (nf-app) picks its engine. Stubs stand in for the native package and for platform RAM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const fdd = require("../hooks/fdd.js");
const GIB = 1024 ** 3;
const PGLITE_MIN = 3.5 * GIB;

function httpWith(bytes) {
  return { get: async () => ({ data: { resources: [{ memory: { totalBytes: bytes } }] } }) };
}

test("auto with DuckDB loadable is server-side duckdb at 1 GiB and at 16 GiB", async () => {
  const small = await fdd.pickEngine(httpWith(GIB), "auto", undefined, () => true, () => true);
  const big = await fdd.pickEngine(httpWith(16 * GIB), "auto", undefined, () => true, () => true);
  assert.deepEqual(small, { kind: "duckdb", note: "" });
  assert.deepEqual(big, { kind: "duckdb", note: "" });
  const unset = await fdd.pickEngine(httpWith(16 * GIB), undefined, undefined, () => true, () => true);
  assert.equal(unset.kind, "duckdb");
});

test("auto with a timescale option stays Timescale and does not consult RAM", async () => {
  const picked = await fdd.pickEngine(httpWith(16 * GIB), "auto", { host: "db" }, () => true, () => true);
  assert.deepEqual(picked, { kind: "timescale", note: "" });
  assert.equal((await fdd.pickEngine(httpWith(GIB), "timescale", undefined, () => true, () => true)).kind, "timescale");
});

test("explicit duckdb with a timescale option still runs duckdb when the package loads", async () => {
  const picked = await fdd.pickEngine(httpWith(16 * GIB), "duckdb", { host: "db" }, () => true, () => true);
  assert.equal(picked.kind, "duckdb");
  assert.equal(picked.note, "");
});

test("a missing @duckdb/node-api fails at 1 GiB and at 16 GiB; RAM does not pick an engine", async () => {
  await assert.rejects(
    fdd.pickEngine(httpWith(GIB), "auto", undefined, () => true, () => false),
    /does not fall back to SQLite or PGlite/);
  await assert.rejects(
    fdd.pickEngine(httpWith(16 * GIB), "auto", undefined, () => false, () => false),
    /@duckdb\/node-api is not loadable/);
  await assert.rejects(
    fdd.pickEngine(httpWith(PGLITE_MIN), "duckdb", { host: "db" }, () => true, () => false),
    /set engine to "timescale"/);
});

test("explicit sqlite and pglite stay selected and are marked deprecated", async () => {
  const sqlite = await fdd.pickEngine(httpWith(16 * GIB), "sqlite", undefined, () => true, () => true);
  const pglite = await fdd.pickEngine(httpWith(GIB), "pglite", undefined, () => false, () => true);
  assert.equal(sqlite.kind, "sqlite");
  assert.equal(pglite.kind, "pglite");
  assert.match(sqlite.note, /deprecated/);
  assert.match(pglite.note, /@duckdb\/node-api/);
});

test("explicit duckdb that cannot load fails even when a timescale option is set", async () => {
  await assert.rejects(
    fdd.pickEngine(httpWith(GIB), "duckdb", { host: "db" }, () => true, () => false),
    /does not fall back to SQLite or PGlite/);
});

test("an unknown engine name is rejected", async () => {
  await assert.rejects(fdd.pickEngine(httpWith(GIB), "wasm", undefined, () => true, () => true), /unknown engine/);
});
