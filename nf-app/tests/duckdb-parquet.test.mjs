// node --test nf-app/tests/duckdb-parquet.test.mjs
// Server-side Node DuckDB writes Parquet and reads it back on a new connection. No Python process.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine, releaseDuckDb } = require("../hooks/lib/engines.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));

let unavailable = "";
try { await import("@duckdb/node-api"); } catch (e) { unavailable = e.message; }
const opts = { skip: unavailable ? `@duckdb/node-api not loadable: ${unavailable}` : false };

const FROM = Date.parse("2026-06-01T00:00:00Z");
const TO = FROM + 3600e3;

function input(rows) {
  return {
    historyColumns: [{ name: "fan_status", type: "double" }],
    history: rows,
    weather: [],
    sensorHistory: [],
    sweepSeries: [],
    pointIds: { fan_status: "11111111-1111-1111-1111-111111111111" },
    siteId: "site-1",
    equipId: "AHU-1",
    window: { from: FROM, to: TO },
  };
}

test("parquet history survives a new connection and does not duplicate a row", opts, async () => {
  const dir = mkdtempSync(join(tmpdir(), "openfdd-parquet-"));
  try {
    const first = await createEngine({ kind: "duckdb", pack, config: { parquetDir: dir, retentionDays: 0 } });
    const row = { equipment_id: "AHU-1", ts: FROM, fan_status: 1 };
    const n1 = await first.load(input([row]));
    assert.equal(n1, 1);
    const wide = await first.windowHistory("AHU-1");
    assert.equal(wide.length, 1);
    assert.equal(wide[0].ts, FROM);
    assert.equal(wide[0].fan_status, 1);
    const plan = await first.explain("SELECT count(*) FROM history");
    assert.match(plan, /PARQUET|read_parquet/i);
    const cov = first.coverage(["11111111-1111-1111-1111-111111111111"]);
    assert.equal(cov["11111111-1111-1111-1111-111111111111"].min_ms, FROM);
    await first.close();
    await releaseDuckDb();

    const second = await createEngine({ kind: "duckdb", pack, config: { parquetDir: dir, retentionDays: 0 } });
    const n2 = await second.load(input([]));
    assert.equal(n2, 1, "the window is read from Parquet, not from this run's empty input");
    const n3 = await second.load(input([row]));
    assert.equal(n3, 1, "the same timestamp is one row after a second write");
    const settings = await second.settings();
    assert.equal(settings.autoinstall, false);
    assert.equal(settings.autoload, false);
    assert.equal(settings.time_zone, "UTC");
    assert.match(String(settings.temp_directory), /tmp/);
    await second.close();
  } finally {
    await releaseDuckDb();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("retention deletes a date partition older than the window", opts, async () => {
  const dir = mkdtempSync(join(tmpdir(), "openfdd-parquet-"));
  const old = join(dir, "samples", "point_id=old-point", "date=2000-01-01");
  mkdirSync(old, { recursive: true });
  writeFileSync(join(old, "part-old.parquet"), "");
  try {
    const eng = await createEngine({ kind: "duckdb", pack, config: { parquetDir: dir, retentionDays: 1 } });
    await eng.load(input([]));
    await eng.close();
    assert.equal(existsSync(old), false);
  } finally {
    await releaseDuckDb();
    rmSync(dir, { recursive: true, force: true });
  }
});
