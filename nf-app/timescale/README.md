# Open-FDD on NF's TimescaleDB (FULL edition)

The Lite edition (Pi) reads NF's REST history and runs the rule pack in SQLite/PGlite. The FULL edition
reads the history NF's **Timescale/Postgres northbound connector** already writes
(docs.normal.dev/timescale: tables `instances`, `points`, `data`, one view per layer), runs the 77 Postgres
rules **inside the database**, and keeps results and long-range history there with a size-based retention cap.

| File | Purpose |
| --- | --- |
| `adapter_nf.sql` | The ONLY file that knows NF's DDL: view `openfdd.nf_samples(point_uuid text, ts timestamptz, value double precision)` |
| `install.sql` | Schema `openfdd`: `config`, `fdd_results` hypertable, `enforce_size_cap()`, `size_cap_job()` + daily job, `history_buckets()` |
| `../hooks/lib/timescale.js` | `connect`, `install`, `loadHistory`, `runRules`, `writeResults`, `maybeEnforceCap`, `historyRoute` |
| `../hooks/history.js` | On-request hook `history`: long-range bucketed history as JSON (capped ~200 KB) |
| `test/` | Docker TimescaleDB + synthetic NF-like seed + `node:test` suite |

Dependency: npm `pg` 8.23.1 (add to `nf-app/package.json` dependencies). Image: `timescale/timescaledb:2.31.0-pg17`.

## Run the tests

```
docker compose -f nf-app/timescale/test/docker-compose.yml up -d
PGURL=postgres://postgres:example@localhost:55432/postgres node --test nf-app/timescale/test/timescale.test.mjs
```

Without `PGURL` (or with the DB down) the suite skips with a message. The suite re-seeds the DB before and after
(`seed_nf_like.sql`: ~60 days of 5-minute AHU data in degF/inH2O), so you can poke at a fresh DB afterwards:
`docker exec -it openfdd-timescale-test psql -U postgres`. Stop and delete it:
`docker compose -f nf-app/timescale/test/docker-compose.yml down -v`.

## Set up on a live NF box

1. In the NF console enable the **Timescale/Postgres connector** (northbound) pointing at your database; wait for data.
2. Look at the real DDL: `psql ... -c '\d data' -c '\d points' -c '\d instances' -c '\dv'`.
3. Edit `adapter_nf.sql` if it differs (schema, column names, value type, how the point uuid is stored; the
   `point_uuid` it returns must equal the NF point uuid the hook binds). Nothing else needs to change.
4. Apply: `psql "$PGURL" -f nf-app/timescale/adapter_nf.sql -f nf-app/timescale/install.sql` (or let the hook call
   `install()`). Safe to re-run. If the role cannot `add_job`, install prints a NOTICE and the fdd hook enforces the
   cap once a day instead (`openfdd.config.job_registered` says which).
5. Hook config (secrets from env or NF hook settings, never the repo):
   ```json
   "timescale": { "host": "127.0.0.1", "port": 5432, "database": "nf", "user": "openfdd", "passwordEnv": "OPENFDD_PG_PASSWORD" }
   ```
   (or `{ "connectionString": "postgres://..." }`). Used by the `fdd` and `history` hooks.
6. The `openfdd` DB role needs: SELECT on NF's tables, CREATE on the database (schema `openfdd`, schema `fdd` for
   the pack's helper functions, temp tables), and to own the NF hypertables or be a superuser for the size cap to
   drop their chunks.

## Retention cap (default 100 GB)

`openfdd.enforce_size_cap(max_bytes)` drops the oldest chunks (by chunk end time, across NF's data hypertable(s) and
`openfdd.fdd_results`) until `sum(hypertable_size())` is at or below the cap. The newest chunk of every hypertable
is never dropped, granularity is one chunk, and it returns a JSON summary (`before_bytes`, `after_bytes`,
`chunks_dropped`, `reached_cap`, `dropped[]`). Hypertables are discovered from
`timescaledb_information.hypertables`; time dimensions must be timestamp-typed (integer-time hypertables are left alone).

Change the cap (bytes) and run it by hand:

```sql
UPDATE openfdd.config SET value = to_jsonb(53687091200::bigint) WHERE key = 'max_bytes';   -- 50 GB
SELECT openfdd.enforce_size_cap(openfdd.max_bytes());
```

Tip: with a 100 GB cap, give NF's data hypertable a sensible `chunk_time_interval` (1 day to 1 week) so the cap
can be hit closely, and consider TimescaleDB compression on old chunks (size counts compressed size).
