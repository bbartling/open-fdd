// node --test nf-app/tests/engine-badge.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { engineBadgeText, appOptions } = require("../static/version.js");

test("engine badge matches the NF plugin auto rule and never says WASM", () => {
  assert.equal(engineBadgeText({}), "DuckDB");
  assert.equal(engineBadgeText({ engine: "auto" }), "DuckDB");
  assert.equal(engineBadgeText({ engine: "auto", timescale: "{\"host\":\"db\"}" }), "Timescale");
  assert.equal(engineBadgeText({ engine: "timescale" }), "Timescale");
  assert.equal(engineBadgeText({ engine: "duckdb", timescale: "{\"host\":\"db\"}" }), "DuckDB");
  assert.equal(engineBadgeText({ engine: "sqlite" }), "SQLite (deprecated)");
  assert.equal(engineBadgeText({ engine: "pglite" }), "PGlite (deprecated)");
  assert.equal(appOptions({ applications: [{ id: "open-fdd", options: { engine: "auto" } }] }).engine, "auto");
  assert.equal(appOptions({ applications: [{ id: "other" }] }), null);
});
