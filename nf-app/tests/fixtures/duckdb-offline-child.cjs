// Child process of duckdb-engine.test.mjs (#1645): runs the DuckDB engine with the extension repository pointed at an
// unreachable host and an empty extension directory, from an empty working directory, so any download or disk spill
// would either fail or leave a file behind. Prints one JSON line.
//   node duckdb-offline-child.cjs <empty extension dir>
"use strict";
const path = require("path");
const fs = require("fs");
const { createEngine, releaseDuckDb } = require("../../hooks/lib/engines.js");
const { buildDataset } = require("./synthetic_dataset.js");

const pack = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "rules", "pack-postgres.json"), "utf8"));
const RULES = ["FC1", "UTIL-MONTHLY", "SV-STALE", "OAT-METEO", "FAN-RUNTIME-HOURS"];

(async () => {
  const out = { rules: {}, timeline_rows: 0, oom: null };
  const eng = await createEngine({ kind: "duckdb", pack, config: { memoryLimit: "128MB", threads: 1,
    extraSettings: { custom_extension_repository: "http://127.0.0.1:9", extension_directory: process.argv[2] } } });
  try {
    out.settings = await eng.settings();
    await eng.load(buildDataset(pack, { equipments: 2, days: 3, stepSeconds: 300 }));
    for (const rid of RULES) {
      out.rules[rid] = (await eng.query(rid)).length;
      out.timeline_rows += (await eng.timeline(rid)).length;
    }
    // A sort far over the 128MB cap: with spilling off it must fail (out of memory), not write to the working directory.
    try {
      await eng.query("FC1", { sql: "SELECT r, md5(CAST(r AS VARCHAR)) || repeat('x', 200) AS s FROM range(4000000) t(r) ORDER BY s" });
      out.oom = "no error";
    } catch (e) { out.oom = String(e.message).split("\n")[0]; }
  } finally {
    await eng.close();
    await releaseDuckDb();
  }
  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.message) }) + "\n"); process.exit(1); });
