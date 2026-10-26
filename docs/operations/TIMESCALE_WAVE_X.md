# Wave-X Timescale 3.6.0 — bring-up

> **Mandate (current, 4.0+):** **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing.** Parquet, Arrow, Arrow IPC, Feather and DataFusion are prohibited in product storage, caching, execution and dependencies. Canonical text: [`openfdd_agent_spec/DATA_CONTRACT.md` § Storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory). The 3.6.0 notes below are kept as history; where they differ, the mandate wins.

Soft-OPEN ≠ FQ. Historical (3.6.0): "Fieldbus BACnet/Modbus unchanged" — fieldbus is archived on 4.0. No dual-write
(`dual_write` / dual-path false). Default binary Timescale-only
(`legacy-datafusion` / `legacy-parquet` OFF).

**Soft-OPEN Railway / ACME:** no site backups unless Ben asks — Timescale-only
historian, dual-write false. Soft-OPEN is not full qualification.

**Soft-OPEN R8d tip-safe:** no Soft-OPEN agent Railway/DB/volume backups; Parquet
compaction/budget Soft-OPEN N/A on Timescale tip (the remaining `crates/fdd_store`
Parquet compaction and budget code is a known gap being removed in Wave P2, not permitted); Timescale WAL/PITR/restore
remain FQ-open. See [`docs/softopen/SOFTOPEN_WAL_RESTORE_R8d.md`](../softopen/SOFTOPEN_WAL_RESTORE_R8d.md).

**Morning / reboot:** ART one-pager
`/tmp/openfdd-softopen/3.6.0/REBOOT_SAFE.md` (+ `DONE.md`, Grok prompt under
`grok/`). ADR: [`adr-010-timescale-hard-cutover.md`](../architecture/adr-010-timescale-hard-cutover.md).
**Next tip:** 3.6.1 patch train — [`.cursor/plans/post_wave_x_361_patch_ghcr_20261012.plan.md`](../../.cursor/plans/post_wave_x_361_patch_ghcr_20261012.plan.md).

## Auto-seed stack

```bash
# Timescale core + schema init
docker compose -p openfdd-wavex-ts -f docker/compose.timescale.core.yml up -d timescale

# Seed warehouse registry + BUILDING_50 (ART defaults)
docker run --rm --network openfdd-wavex-ts_default \
  -e OPENFDD_DATABASE_URL='postgresql://openfdd:openfdd_dev_only@timescale:5432/openfdd' \
  -e OPENFDD_SEED_WAREHOUSE_DIR=/seeds/warehouse \
  -e OPENFDD_SEED_BUILDING50_DIR=/seeds/BUILDING_50 \
  -e OPENFDD_SQL_ROOT=/sql \
  -e OPENFDD_AUTO_SEED=1 \
  -v "$PWD/scripts/timescale:/scripts:ro" \
  -v "$PWD/sql:/sql:ro" \
  -v /tmp/openfdd-softopen/3.6.0/seeds/warehouse_handoff/open-fdd-warehouse-handoff:/seeds/warehouse:ro \
  -v /tmp/openfdd-softopen/3.6.0/seeds/BUILDING_50/BUILDING_50:/seeds/BUILDING_50:ro \
  python:3.12-slim \
  bash -lc 'pip install -q "psycopg[binary]" && python /scripts/auto_seed.py'

# Product recipes attach Timescale overlay automatically (portal / react / csv).
# `up` reuses the openfdd-timescale volume. Init SQL runs only on an empty volume.
./scripts/openfdd_stack_up.sh portal
```

`auto_seed.py` copies BUILDING_50 only when that site has no `sample` rows.
If rows or a previous seed exist, it exits without deleting them.
A reload requires both `OPENFDD_SEED_FORCE=1` and `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`.
A full historian wipe is a separate one-shot command, `scripts/timescale/purge_historian.py`,
with a new `OPENFDD_RESET_DB` token and `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`.
The same token does not wipe again. Leave `OPENFDD_RESET_DB` unset on updates.

Env: `OPENFDD_DATABASE_URL`, `OPENFDD_HISTORIAN=timescale`, `OPENFDD_FDD_ENGINE=postgres-sql`, `OPENFDD_SQL_ROOT`.

Central tip must be Wave-X GHCR build (local docker-build of central discouraged on mintbench).
