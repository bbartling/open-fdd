// The Lite manifest ships the Full FDD hook. This assembles that file map and runs it:
// server-side Node DuckDB, the Postgres rule pack, a result row. No sql.js and no PGlite.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const liteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(path.join(liteRoot, "app.json"), "utf8"));

const STEP = 300;
const NOW = Date.parse("2026-07-05T12:02:00Z");
const pt = (uuid, name, markers, extra = {}) => ({
  uuid, name, layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", markers: ["point", "his", ...markers].join(","), dis: name, ...extra },
});
const MODEL = [
  { uuid: "s", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site", tz: "America/Chicago" } },
  { uuid: "e", name: "BLR-1", pointType: "EQUIPMENT", attrs: { id: "BLR-1", siteRef: "site-a", markers: "equip,boiler" } },
];
const PUMP = pt("u-PUMP", "HW-PUMP-S", ["pump", "run", "sensor"], { equipRef: "BLR-1", unit: "" });
const WEB = pt("u-WEB", "oa_dry_bulb_web", ["weather", "outside", "air", "temp"], { unit: "degF" });

function http(points) {
  const writes = { points: [], data: [] };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? MODEL : points } };
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/points/data") {
        for (const x of body.points) writes.data.push({ uuid: x.uuid, values: x.values });
        return { data: { success: true } };
      }
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/point/data?")) {
        const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        const val = { "u-PUMP": 1, "u-WEB": 77 };
        return { data: { data: uuids.map((uuid) => ({ uuid, values: Array.from({ length: 288 }, (_, i) => ({ ts: new Date(NOW - 24 * 3600e3 + i * STEP * 1e3).toISOString(), double: val[uuid] })) })) } };
      }
      if (p.startsWith("/api/v1/sites") || p.startsWith("/api/v1/schedules")) throw new Error("HTTP 404");
      throw new Error("unexpected GET " + p);
    },
  };
}

function assemble() {
  const dir = mkdtempSync(path.join(liteRoot, "..", "nf-app", ".tmp-lite-fdd-"));
  for (const [nfPath, rel] of Object.entries(manifest.files)) {
    const src = path.resolve(liteRoot, rel);
    const dest = path.join(dir, nfPath.replace(/^\//, ""));
    mkdirSync(path.dirname(dest), { recursive: true });
    writeFileSync(dest, readFileSync(src));
  }
  return dir;
}

test("Lite's shipped FDD hook writes an HW-OAT-1 result on Node DuckDB", async () => {
  const dir = assemble();
  const hookPath = path.join(dir, "hooks", "fdd.js");
  const require = createRequire(hookPath);
  try {
    const hook = require(hookPath);
    const h = http([PUMP, WEB]);
    const logs = [];
    const summary = await hook.runFdd({
      sdk: { http: h, logEvent: (m) => logs.push(m) },
      config: { engine: "duckdb", parquetDir: path.join(dir, "parquet") },
      now: NOW,
    });
    assert.equal(summary.errors, 0, logs.join("\n"));
    const hit = summary.results.find((r) => r.rule === "HW-OAT-1" && r.equip === "BLR-1");
    assert.ok(hit && hit.fault, JSON.stringify(summary.results));
    assert.ok(logs.some((l) => /engine duckdb/.test(l)), logs.join("\n"));
    assert.ok(!logs.some((l) => /sql\.js|pglite|wasm/i.test(l)), logs.join("\n"));
  } finally {
    try { createRequire(hookPath)(path.join(dir, "hooks", "lib", "engines.js")).releaseDuckDb(); } catch { /* not loaded */ }
    rmSync(dir, { recursive: true, force: true });
  }
});
