---
title: Upgrading to 5.0.16
parent: Normal Framework
nav_order: 2
---

# Upgrading to 5.0.16

Applies to Full installations that use the Timescale engine. Lite and the `sqlite` / `pglite` engines have no persistent
tables and need nothing.

## What changes

| Before (schema 3) | After (schema 4) |
| --- | --- |
| `openfdd.fdd_results` (hypertable on `run_ts`) | `fdd.rule_result` (hypertable on `window_end`), shared core schema |
| `openfdd.retention_log` | gone; the last real retention result is `openfdd.config` key `retention_last` |
| none | `fdd.point` (bound points mirrored by the hook), `fdd.rule_config`, view `fdd.input_sample` |
| `openfdd.nf_samples` | unchanged (native units); the loader now reads `fdd.input_sample` (SI) |

## How to upgrade

Push the new app version with `nf_app_sync.py install`. The first `fdd` run (or the installer role running
`timescale/core.sql`, `adapter_nf.sql`, `install.sql` in that order, with `psql -v ON_ERROR_STOP=1 -1`) upgrades in place, in one transaction:

1. creates the core tables and the view, makes `fdd.rule_result` a hypertable;
2. copies every `openfdd.fdd_results` row into `fdd.rule_result` (`created_at` = old `run_ts`, status from `fault_hours`,
   empty `rule_hash` / `config_hash`, a flagged placeholder window where the old row had none);
3. **only if the number of copied rows equals the number of source rows** drops `openfdd.fdd_results` and
   `openfdd.retention_log`; otherwise the upgrade raises and leaves everything as it was;
4. sets `schema_version` 4.

`doctor` / the schema probe report `core_ok` (core tables and view present). Nothing needs to be done by hand.

## Rolling back

The old tables are dropped in this release, so a rollback is: reinstall the previous app version AND run its
`timescale/install.sql` as the installer role (it recreates `openfdd.fdd_results` and sets `schema_version` back to 3;
the old probe cannot tell, since 4 >= 3). Results written before the upgrade now live in `fdd.rule_result` only, and
results written between the upgrade and the rollback are not copied back. Take a `pg_dump -n openfdd -n fdd` first if
that history matters.

## Things to know

- `fdd.point` is a mirror of the model: the hook rewrites a piece's rows before every load. Do not edit it by hand.
- Retention scope is now the schemas `openfdd` and `fdd` plus the allowlist; the size cap counts `fdd.rule_result`.
- The `status` of results written before the upgrade is derived (`fault_hours` > 0 FAULT, 0 PASS, none INCONCLUSIVE).
