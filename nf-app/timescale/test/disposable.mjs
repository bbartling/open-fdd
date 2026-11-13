// Safety rails for the destructive Timescale tests (the seed drops public.data / points / instances CASCADE and
// the retention tests drop chunks). Nothing here ever runs DDL on a database it did not create itself:
//   1. OPENFDD_TS_TEST_DISPOSABLE=1 must be set (explicit opt-in);
//   2. the runner creates its OWN database openfdd_test_<random> through the admin URL (PGURL) and puts a marker
//      (database comment "openfdd-ts-test-disposable:<random token>") on it;
//   3. assertDisposable() refuses unless opt-in + db name prefix + the exact marker token of THIS process match.
// Credentials are never printed: only the generated database name is logged.
import { randomBytes } from "node:crypto";

export const MARKER_PREFIX = "openfdd-ts-test-disposable:";
export const OPT_IN = "OPENFDD_TS_TEST_DISPOSABLE";
const quoteId = (s) => '"' + String(s).replace(/"/g, '""') + '"';

export const newToken = () => randomBytes(8).toString("hex");
export const dbNameFor = (token) => `openfdd_test_${token}`;

/** Same URL with another database name (the password stays inside the URL object, never logged). */
export function urlForDb(adminUrl, dbName) {
  const u = new URL(adminUrl);
  u.pathname = "/" + dbName;
  return u.toString();
}

/** Throws unless the opt-in is set and `client` is connected to a database carrying this process's marker. */
export async function assertDisposable(client, token, optIn = process.env[OPT_IN]) {
  if (optIn !== "1") throw new Error(`refused: ${OPT_IN}=1 is not set`);
  const { rows } = await client.query(
    "SELECT current_database() AS db, shobj_description(oid, 'pg_database') AS marker FROM pg_database WHERE datname = current_database()");
  const { db, marker } = rows[0];
  if (!db.startsWith("openfdd_test_")) throw new Error(`refused: database "${db}" is not an openfdd_test_ database`);
  if (marker !== MARKER_PREFIX + token) throw new Error(`refused: database "${db}" does not carry this run's disposable marker`);
}

/** Creates a database through the ADMIN connection; marked unless token is null. Returns its name. */
export async function createDb(admin, name, token) {
  await admin.query(`CREATE DATABASE ${quoteId(name)}`);
  if (token) await admin.query(`COMMENT ON DATABASE ${quoteId(name)} IS '${MARKER_PREFIX}${token}'`);
  return name;
}

export async function dropDb(admin, name) {
  await admin.query(`DROP DATABASE IF EXISTS ${quoteId(name)} WITH (FORCE)`);
}

/** A client wrapper whose every query first re-checks the guard (so a stray DDL cannot reach a foreign database). */
export function guarded(client, token) {
  return {
    raw: client,
    async query(...args) {
      // transaction control is not DDL, and the guard query itself would fail inside an aborted transaction
      if (!(typeof args[0] === "string" && /^(BEGIN|COMMIT|ROLLBACK|SAVEPOINT \w+|ROLLBACK TO SAVEPOINT \w+|RELEASE SAVEPOINT \w+)$/.test(args[0]))) await assertDisposable(client, token);
      return client.query(...args);
    },
  };
}
