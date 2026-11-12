// Prints the normalized catalog (columns, constraints, indexes) of the three core tables after executing a core.sql
// in a fresh PGlite (real Postgres). Used by build_core_schema.py (writes core.catalog.json) and tests/test_core_schema.py.
//   node scripts/nf/core_catalog.mjs <path to core.sql>
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const require = createRequire(path.join(root, "nf-app", "package.json"));
const { PGlite } = await import(pathToFileURL(require.resolve("@electric-sql/pglite")).href);

const TABLES = ["point", "rule_config", "rule_result"];
const db = new PGlite();
const sql = readFileSync(process.argv[2], "utf8");
await db.exec(sql);
await db.exec(sql);   // idempotent: the second run must not fail

const out = {};
for (const t of TABLES) {
  const cols = await db.query(
    `SELECT a.attnum, a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull AS not_null,
            pg_get_expr(d.adbin, d.adrelid) AS "default", a.attidentity AS identity
     FROM pg_attribute a
     LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE a.attrelid = $1::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum`, [`fdd.${t}`]);
  const cons = await db.query(
    `SELECT conname AS name, contype AS type, pg_get_constraintdef(oid, true) AS definition
     FROM pg_constraint WHERE conrelid = $1::regclass ORDER BY contype, conname`, [`fdd.${t}`]);
  const idx = await db.query(
    `SELECT c.relname AS name, x.indisunique AS "unique", x.indisprimary AS "primary", am.amname AS method,
            array_to_string(ARRAY(SELECT pg_get_indexdef(x.indexrelid, k + 1, true) || CASE WHEN (x.indoption[k] & 1) = 1 THEN ' DESC' ELSE '' END
                                  FROM generate_series(0, x.indnkeyatts - 1) k ORDER BY k), ', ') AS columns,
            pg_get_expr(x.indpred, x.indrelid) AS predicate
     FROM pg_index x JOIN pg_class c ON c.oid = x.indexrelid JOIN pg_am am ON am.oid = c.relam
     WHERE x.indrelid = $1::regclass ORDER BY c.relname`, [`fdd.${t}`]);
  out[`fdd.${t}`] = {
    columns: cols.rows.map(({ attnum, ...r }) => ({ ...r, identity: r.identity || null })),
    constraints: cons.rows,
    indexes: idx.rows,
  };
}
const extra = await db.query(
  `SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'fdd' AND c.relkind IN ('r','v','m','p') ORDER BY 1`);
out._relations = extra.rows.map((r) => r.relname);
process.stdout.write(JSON.stringify(out, null, 1) + "\n");
await db.close();
