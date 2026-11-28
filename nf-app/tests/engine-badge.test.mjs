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
  assert.match(html, /id="engineBuild"[^>]*>DuckDB build</);
  assert.doesNotMatch(html, /duckdb-wasm|sql-wasm|SQLite|PGlite/);
});
