# Open-FDD on NF's TimescaleDB (FULL edition)

The Lite edition (Pi) reads NF's REST history and runs the rule pack in SQLite/PGlite. The FULL edition
reads the history NF's **Timescale/Postgres northbound connector** already writes
(docs.normal.dev/timescale: tables `instances`, `points`, `data`, one view per layer), runs the 77 Postgres
rules **inside the database**, and keeps results and long-range history there with a size-based retention cap
that only ever touches Open-FDD's own tables (unless you opt a source table in).

| File | Purpose |
| --- | --- |
| `adapter_nf.sql` | The ONLY file that knows NF's DDL: view `openfdd.nf_samples(point_uuid text, ts timestamptz, value double precision)` |
| `install.sql` | Schema `openfdd`: `config`, `fdd_results` hypertable, scoped retention (`retention_scope()`, `enforce_size_cap()`, `retention_preview()`, `retention_log`, `size_cap_job()` + daily job), `history_buckets()`. Re-run to upgrade |
| `../hooks/lib/timescale.js` | `connect`, `install`, `loadHistory`, `runRules`, `writeResults`, `maybeEnforceCap`, `retentionPreview`, `historyRoute` |
| `../hooks/history.js` | On-request hook `history`: long-range bucketed history as JSON (bounded, capped ~200 KB) |
| `test/` | Docker TimescaleDB, synthetic NF-like seed, `node:test` suites (see below) |

Dependency: npm `pg` 8.23.1 (add to `nf-app/package.json` dependencies). Image: `timescale/timescaledb:2.31.0-pg17`.

## Run the tests

```
docker compose -f nf-app/timescale/test/docker-compose.yml up -d
OPENFDD_TS_TEST_DISPOSABLE=1 PGURL=postgres://postgres:example@localhost:55432/postgres node --test nf-app/timescale/test/timescale.test.mjs
node --test nf-app/timescale/test/bounds.test.mjs          # no database needed
```

The Docker suite is **destructive by design** (the seed drops `public.data`/`points`/`instances`, the retention tests
drop chunks), so it is fenced:

- It skips unless `OPENFDD_TS_TEST_DISPOSABLE=1` is set. `PGURL` is only the **admin** connection.
- The runner creates its own database `openfdd_test_<random>` through that admin URL, puts a marker on it (database
  comment `openfdd-ts-test-disposable:<random token>`), runs everything there and drops the database at the end.
- Every statement goes through a guard that refuses unless the opt-in is set, the database name starts with
  `openfdd_test_` and the marker token is this run's. The seed script also refuses on its own (before any `DROP`) in a
  database without a marker. A negative test checks the admin database, an unmarked database and a foreign-marked one.
- Credentials are never logged (only the generated database name is).

Stop and delete the container: `docker compose -f nf-app/timescale/test/docker-compose.yml down -v`.

## Set up on a live NF box

1. In the NF console enable the **Timescale/Postgres connector** (northbound) pointing at your database; wait for data.
2. Look at the real DDL: `psql ... -c '\d data' -c '\d points' -c '\d instances' -c '\dv'`.
3. Edit `adapter_nf.sql` if it differs (schema, column names, value type, how the point uuid is stored; the
   `point_uuid` it returns must equal the NF point uuid the hook binds). Nothing else needs to change.
4. Apply **as the installer role**: `psql "$PGURL" -f nf-app/timescale/adapter_nf.sql -f nf-app/timescale/install.sql`
   (or let the hook call `install()` on first run, which needs the same rights). Safe to re-run. If the role cannot
   `add_job`, install prints a NOTICE and the fdd hook enforces the cap once a day instead
   (`openfdd.config.job_registered` says which).
5. Hook config (secrets from env, never the repo), for both the `fdd` and `history` hooks:
   ```json
   "timescale": { "host": "127.0.0.1", "port": 5432, "database": "nf", "user": "openfdd_rt", "passwordEnv": "OPENFDD_PG_PASSWORD" }
   ```
   (or `{ "connectionString": "postgres://..." }`). Set `"engine": "timescale"` (or leave `engine` unset / `"auto"`)
   in the `fdd` hook config; the connector alone does not switch Open-FDD to this engine, the config does. With
   `engine: "timescale"` and no `timescale` config the hook fails with a clear error instead of falling back.

## Installer role vs runtime role

| | Installer (run `install.sql`, owns the job) | Runtime (the hooks connect as this role) |
| --- | --- | --- |
| Purpose | create / upgrade schema `openfdd`, register or alter the daily job, create the `timescaledb` extension if missing | read NF history, run rules, write results, answer `history` |
| NF's `data` / `points` / `instances` | `SELECT` (adapter view) | `SELECT` only |
| Schema `openfdd` | owner / `CREATE` | `USAGE` + `SELECT, INSERT, UPDATE, DELETE` on its tables, `EXECUTE` on its functions (write on schema `openfdd` only) |
| Schema `fdd` (the pack's helper SQL) | `CREATE` | `USAGE, CREATE` on schema `fdd` (pre-create it as installer) |
| Database | `CREATE` | `TEMP` (rules run on TEMP tables) |
| Other apps' tables | nothing | nothing |
| `add_job` / `drop_chunks` | job owner; to trim an allowlisted NF table it must own that hypertable (or be superuser) | not needed |

Example grants (installer connected to the NF database, runtime role `openfdd_rt`):

```sql
GRANT USAGE ON SCHEMA public TO openfdd_rt;
GRANT SELECT ON public.data, public.points, public.instances TO openfdd_rt;
GRANT USAGE ON SCHEMA openfdd TO openfdd_rt;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA openfdd TO openfdd_rt;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA openfdd TO openfdd_rt;
CREATE SCHEMA IF NOT EXISTS fdd;
GRANT USAGE, CREATE ON SCHEMA fdd TO openfdd_rt;
GRANT TEMP ON DATABASE nf TO openfdd_rt;
```

The retention job runs as the job owner (the installer), not as the runtime role. A runtime role without install
rights still works for rules and history; if the schema is older than this release the hook refuses to run
retention (it reports a clear error) until `install.sql` is run once as the installer.

## Retention (default 100 GB, Open-FDD tables only)

`openfdd.enforce_size_cap(max_bytes)` drops the oldest chunks (by chunk end time) **in scope** until the scope's
`hypertable_size()` total is at or below the cap. **Scope** (`openfdd.retention_scope()`) = every hypertable in schema
`openfdd` (today `openfdd.fdd_results`) plus the opt-in allowlist. NF's own connector tables and other apps' tables are
never touched by default. The newest chunk of every hypertable is never dropped and granularity is one chunk.
Time dimensions must be timestamp-typed (integer-time hypertables are left alone).

Opt-in for NF / source history (empty by default):

```sql
UPDATE openfdd.config SET value = '["public.data"]'::jsonb WHERE key = 'retention_allowlist';
```

The allowlist is a JSON array of fully qualified `schema.table` names. It is validated against the existing hypertables
every run; a bad value (unknown name, a regular table, `_timescaledb*`, not an array of strings) **fails closed**:
the run drops nothing (not even Open-FDD chunks) and returns `status = refused_allowlist` with the reason.
Listing a source table makes the cap apply to the combined size, so size the cap for that.

Every run returns an explicit JSON result (also logged to `openfdd.retention_log`):

| `status` | Meaning |
| --- | --- |
| `under_cap` / `cap_reached` | scope fits the cap (nothing / something was dropped) |
| `chunk_budget_exhausted` | still over the cap but `config.max_chunks_per_call` (default 100) chunks were dropped; the next run continues |
| `no_progress` | still over the cap and nothing droppable is left (only newest chunks remain) or drops stopped shrinking the total: the cap is unreachable, raise it or allowlist more |
| `refused_allowlist` | invalid allowlist, nothing dropped |
| `error` | a drop failed (for example the role does not own that hypertable); `error` has the message |
| `skipped_locked` | another run holds the lock |

Preview (dry run, drops and writes nothing; `would_drop[]` lists chunks with sizes):

```sql
SELECT jsonb_pretty(openfdd.retention_preview(openfdd.max_bytes()));
SELECT jsonb_pretty(openfdd.retention_preview(53687091200));   -- what a 50 GB cap would drop
```

Change the cap (bytes) and run it by hand:

```sql
UPDATE openfdd.config SET value = to_jsonb(53687091200::bigint) WHERE key = 'max_bytes';   -- 50 GB
SELECT openfdd.enforce_size_cap(openfdd.max_bytes());
```

### Upgrading an older install

Earlier releases dropped chunks across **every** hypertable in the database (including NF's `data`) on a daily job.
Re-running `install.sql` as the installer upgrades in place: the old function bodies are replaced (same names), the
existing `size_cap_job` job keeps its id and schedule but is altered and marked scoped (`config.scope`), duplicate jobs
are removed, `retention_allowlist` (empty) and `max_chunks_per_call` are added, and `config.schema_version` becomes 2.
There is never a second job and no old global job left running. Until the upgrade is applied, the hooks refuse to run
retention themselves (`maybeEnforceCap` throws "older than this release"); the old database job keeps its old behaviour
until `install.sql` runs, so run it before relying on the cap.

Tip: with a 100 GB cap, give NF's data hypertable a sensible `chunk_time_interval` (1 day to 1 week) if you allowlist
it so the cap can be hit closely, and consider TimescaleDB compression on old chunks (size counts compressed size).

## Long-range history hook

`POST .../hooks/history` with `{"args": {"uuids": [...], "from": "...", "to": "...", "bucket": "1 hour"}}` is bounded
before it queries: positive finite times with `from < to`, span at most 3660 days, bucket at least 1 minute, and
(buckets per series) x (uuids) at most `maxPoints` (200000). A request that is too fine is **coarsened** to a larger
bucket (`coarsened: true`, `requested_bucket` kept) or rejected (`"coarsen": false`). The query runs in a transaction
with `SET LOCAL statement_timeout` (20 s) and `LIMIT maxPoints + 1`; the answer carries `coverage` (per-uuid buckets /
samples / first / last, uuids without data), `truncated` and `max_points`. Limits are server side, in hook config
`history` (`maxPoints`, `maxSpanDays`, `minBucketSec`, `statementTimeoutMs`, `maxBytes`, `maxUuids`), never from the request.

Scales (issue #1541): `loadHistory` never decides a scale itself. The `fdd` hook's `siPlan` (driven by `sql/fdd/role_scales.json`)
decides per role and passes `fractionRoles` (roles divided by 100: declared-% fraction or boolean roles) and `booleanRoles`
(bucket average must lie in [0, 1], else NULL). Fraction roles with no unit are skipped by `siPlan` and never reach SQL, so their
rules are not assessed. Without the two arrays a role is just an SI conversion by unit.
