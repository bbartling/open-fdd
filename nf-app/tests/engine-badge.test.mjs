// node --test nf-app/tests/engine-badge.test.mjs
// The DuckDB build stamps its label in the page. There is no options badge for SQLite, PGlite, or WASM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("the DuckDB build page names DuckDB and does not ship a WASM engine", () => {
  const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
  const build = JSON.parse(readFileSync(new URL("../static/engine-build.json", import.meta.url), "utf8"));
  assert.equal(build.id, "duckdb");
  assert.equal(build.library, "@duckdb/node-api");
  assert.match(html, /id="engineBuild"[^>]*>DuckDB backend</);
  assert.doesNotMatch(html, /DuckDB build|Timescale build|Open-FDD Lite|>Full</);
  const version = readFileSync(new URL("../../shared/static/version.js", import.meta.url), "utf8");
  assert.ok(version.indexOf("whenAuthReady") < version.indexOf("hooks/schema"), "schema runs after auth");
  assert.match(version, /open-fdd-lite/);
  assert.match(version, /engine_label/);
  assert.doesNotMatch(html, /duckdb-wasm|sql-wasm|SQLite|PGlite/);
});
