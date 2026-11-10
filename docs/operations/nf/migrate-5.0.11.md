---
title: Upgrade to Open-FDD 5.0.11
parent: Operations
---

# Upgrade to Open-FDD 5.0.11

Full splits point history requests into bounded batches. The Faults panel shows a message if history fails to load.
It keeps separate scales for hours and percentages. Points history still omits any bucket that starts before the
current output's unit boundary. The CI HTTP mock rejects oversized GET requests so the large-lane tests exercise
the same class of failure observed at an NF front door.

Each sweep publishes sensor results only for roles it can assess. No sweep emits a sensor result for `zone_flow`.
`duct_static` is a sensor target for SV-RANGE and SV-SPIKE. An eligible sensor without coverage keeps null fault
hours in Timescale and in the NF summary JSON. An assessed sensor with no faults keeps numeric zero. Old 5.0.10
points for excluded roles may still exist. The upgrade preserves their NF history and stops publishing new values.

## Check Timescale before installing Full

Full with the Timescale engine requires Open-FDD schema version 3. Run the release's `nf-app/timescale/install.sql`
as the installer or owner role **before** running the app installer if the schema is behind. On a fresh database,
run `adapter_nf.sql` first. The runtime role is for reads and result writes, while the installer role owns the schema
and `openfdd.nf_samples` view.

### Hand the migration to a DBA without SSH

Send the DBA the release commit and SQL files. The DBA can connect directly to the target database with their usual
PostgreSQL client and credentials. From the release checkout, run the migration as the owner in one transaction:

```sh
psql -X --single-transaction --set ON_ERROR_STOP=1 --file nf-app/timescale/install.sql
```

For a fresh setup, supply `--file nf-app/timescale/adapter_nf.sql` before the install file in the same command.
Have the DBA report the value from `SELECT value FROM openfdd.config WHERE key = 'schema_version';`.
Keep connection settings in the client's protected configuration or environment.

Run `doctor` and the app installer after the schema is ready. They use `psql` on the machine running the CLI
for a read-only probe. If that machine needs a different read-only connection from the hook, set
`NF_TIMESCALE_PREFLIGHT_DSN` through the protected environment. The connection must reach the same database as the
hook. For TLS connections, include `sslmode=verify-full` and protected `sslrootcert`, `sslcert`, or `sslkey` paths
in that URI or keyword DSN; this override supplies the CLI connection and its credentials independently of the
hook's settings. If post-install verification reports a terminal failure, the installer restores the previous app files,
options, and hooks and restarts the app. If a hook is still running when the wait expires, the installer reports
the pending run and preserves predecessor apps. It preserves existing app auth throughout the upgrade.
The app rollback leaves database migrations in place. Lite and Full with an embedded engine skip the Timescale
schema check.
