// OPENFDD_TS_TEST_DISPOSABLE=1 PGURL=postgres://postgres:example@localhost:55432/postgres \
//   node --test nf-app/timescale/test/scratch-contract.test.mjs
// Uses only a newly created, process-marked database and drops it in after().
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createDb, dbNameFor, dropDb, newToken, OPT_IN, urlForDb } from "./disposable.mjs";

const require = createRequire(import.meta.url);
const { Client } = require("pg");
const here = (path) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");
const contract = JSON.parse(here("../../../sql/fdd/input_contract.json"));
const pack = JSON.parse(here("../../rules/pack-postgres.json"));
const ddl = here("../../../sql/fdd/input_contract.sql");
const helpers = here("../../../sql/fdd/postgres/postgres_helpers.sql");
const PGURL = process.env.PGURL;
const token = newToken();
const dbName = dbNameFor(token);
let admin;
let client;
let skip = "";

if (process.env[OPT_IN] !== "1") skip = `${OPT_IN}=1 is not set`;
else if (!PGURL) skip = "PGURL (admin connection) is not set";
else {
  try {
    admin = new Client({ connectionString: PGURL });
    await admin.connect();
    await createDb(admin, dbName, token);
    client = new Client({ connectionString: urlForDb(PGURL, dbName) });
    await client.connect();
    console.log(`# disposable scratch database: ${dbName}`);
  } catch (error) {
    skip = `disposable PostgreSQL unavailable (${error.code || error.message})`;
    if (admin) {
      try { await dropDb(admin, dbName); } catch { /* best effort cleanup */ }
      await admin.end().catch(() => {});
      admin = null;
    }
  }
}
if (skip) console.log(`# SKIPPED: ${skip}`);

after(async () => {
  if (client) await client.end();
  if (admin) {
    await dropDb(admin, dbName);
    await admin.end();
  }
});

function valueFor(role, spec) {
  if (spec.type === "text") return role === "occ_mode" ? "occupied" : "sample";
  switch (spec.scale) {
    case "fraction": return 0.5;
    case "boolean": return 1;
    case "percent_rh": return 50;
    case "si:degC": return 20;
    case "si:Pa": return 100;
    case "si:L/s": return 100;
    case "si:kW": return 10;
    case "si:kWh": return 1;
    case "si:A": return 2;
    case "si:ppm": return 800;
    case "si:count": return 1;
    default: throw new Error(`fixture has no value for ${role} (${spec.scale})`);
  }
}

async function insertRow(table, row) {
  const cols = Object.keys(row);
  const names = cols.map((col) => `"${col}"`).join(", ");
  const params = cols.map((_, i) => `$${i + 1}`).join(", ");
  await client.query(`INSERT INTO ${table} (${names}) VALUES (${params})`, cols.map((col) => row[col]));
}

test("scratch DDL prepares and executes every PostgreSQL rule with SI fixtures", { skip: !!skip }, async () => {
  assert.ok(client && admin);
  await client.query(ddl);
  await client.query(helpers);

  const base = { equipment_id: "fixture-equipment", timestamp_utc: null };
  const roleValues = Object.fromEntries(Object.entries(contract.roles).map(([role, spec]) => [role, valueFor(role, spec)]));
  await insertRow("history", { ...base, ...roleValues, timestamp_utc: "2026-10-01T00:00:00Z" });
  await insertRow("history", { ...base, ...roleValues, timestamp_utc: "2026-10-01T00:05:00Z" });
  await insertRow("history", { ...base, ...roleValues, timestamp_utc: "2026-10-01T00:10:00Z" });
  await insertRow("weather", { timestamp_utc: "2026-10-01T00:00:00Z", oa_t: 20, web_oa_t: 20, web_oa_dp: 10 });
  await insertRow("utility_interval", { timestamp_utc: "2026-10-01T00:00:00Z", kwh: 1 });
  await insertRow("utility_monthly", { billing_period: "2026-10", kwh: 1 });
  for (const [series_id, values] of [["sensor-1", [20, 20, 20]], ["sensor-2", [20, 75, 75]]]) {
    for (const [index, timestamp_utc] of ["00:00:00Z", "00:05:00Z", "00:10:00Z"].entries()) {
      await insertRow("sensor_history", {
        equipment_id: "fixture-equipment", series_id, sensor_role: "sat", unit: "degC",
        timestamp_utc: `2026-10-01T${timestamp_utc}`, value: values[index],
      });
    }
  }

  assert.ok(Object.keys(pack.rules).length > 0, "PostgreSQL rule pack is not empty");
  for (const [index, [ruleId, rule]] of Object.entries(pack.rules).entries()) {
    const statement = rule.sql.trim().replace(/;\s*$/, "");
    const prepared = `scratch_rule_${index}`;
    try {
      await client.query(`PREPARE ${prepared} AS ${statement}`);
      const result = await client.query(`EXECUTE ${prepared}`);
      if (["SV-RATE", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"].includes(ruleId)) {
        assert.deepEqual(rule.output_columns, ["equipment_id", "series_id", "sensor_role", "fault_hours", "covered_hours"], ruleId);
        assert.equal(result.rows.length, 2, `${ruleId} must return one row for each of two same-role sensors`);
        assert.deepEqual(result.rows.map((row) => row.series_id).sort(), ["sensor-1", "sensor-2"]);
        assert.ok(result.rows.every((row) => Number(row.covered_hours) > 0), `${ruleId} must report per-sensor coverage`);
      }
    } catch (error) {
      throw new Error(`${ruleId} failed against the canonical scratch contract: ${error.message}`, { cause: error });
    } finally {
      await client.query(`DEALLOCATE ${prepared}`).catch(() => {});
    }
  }
});
