# Local data budget

> Storage mandate: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([`openfdd_agent_spec/DATA_CONTRACT.md` § Storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)). Telemetry retention belongs to Timescale.

Timescale/PostgreSQL is the only store for telemetry and derived analytics results. Central writes no Parquet, Arrow, or Feather files, so there is no file eviction pool. `OPENFDD_LOCAL_DATA_BUDGET_GIB` and `OPENFDD_DATA_BUDGET_ENABLED` have no product effect.

- `GET /api/data-management/budget` returns `enabled: false` and `parquet_historian_budget: "not_applicable"`.
- `POST /api/data-management/retention/apply` returns 400 (not applicable).
- `GET /api/historian/compaction` reports not applicable. `POST` returns 400.

Database size is managed in PostgreSQL (Timescale retention / compression policies, `VACUUM`). The analytics result cache is the row-capped `analytics_result` table ([ANALYTICS_RESULT_CACHE.md](ANALYTICS_RESULT_CACHE.md)).

Older releases left `history/`, `building=*/` and `analytics_results/` Parquet trees under the storage root. Central does not read them. Remove them by hand after the upgrade; an explicit site delete also removes that site's legacy `building=` directory.

## Update preflight

Reserved free space defaults to **10%** of the disk (`OPENFDD_DISK_RESERVED_FREE_PERCENT`, clamp 1–50). An on-box backup is the size of a second copy of the live workspace and database volume. A ~200 GiB host with a 100 GiB live set does **not** have room for that copy plus the reserve. Skip the full copy or prune until the copy fits. If free space stays under the reserve even after that reclaim, fail closed and do not start the update.

| Decision | Exit | Meaning |
| --- | --- | --- |
| proceed | 0 | backup fits |
| skip backup | 10 | test deploy, or the full copy does not fit and backup is not mandatory |
| prune then backup | 11 | reclaim oldest bytes, then the copy fits |
| fail closed | 20 | free space stays under the reserve, or a required backup cannot fit |

```bash
python3 scripts/openfdd_disk_preflight.py --self-test
./scripts/openfdd_disk_preflight.sh --storage-root /var/openfdd/workspace --full-copy
./scripts/openfdd_disk_preflight.sh --full-copy --apply-prune
```

`scripts/openfdd_maint_update_resume.sh` runs the preflight in metadata-snapshot mode (tag/env pin, not a second historian) before its snapshot. Exit 10 clears that snapshot. Exit 20 refuses the update. A full `tar` of `workspace/` must use `--full-copy` first.

`scripts/openfdd_railway_release.sh` still backs up before a real release. **`OPENFDD_TEST_DEPLOY=1` skips that backup** for any site unless `OPENFDD_BACKUP_ON_UPDATE=1`. The flag is not a site-name branch. Do not treat a test deploy as a production backup drill.

**Historical, superseded by the Timescale-only mandate:** DataFusion spill (`OPENFDD_DATAFUSION_SPILL_DIR`, default `<storage_root>/.datafusion-spill`, `OPENFDD_DATAFUSION_SPILL_MAX_GB` / `_BYTES`) was ephemeral query scratch for the retired DataFusion engine. DataFusion is prohibited on the product path; do not set these variables. A leftover `.datafusion-spill` directory is safe to delete when central is idle.

## Soft-OPEN

Logic and tests ship here. Proof on a real edge disk (update with and without headroom) is a field pass, not this change. Do not delete operator archives to make a lab green. No VERSION bump. Not an FQ claim. Scorecard: [ANALYTICS_RESULT_CACHE.md](ANALYTICS_RESULT_CACHE.md) § Compliance.

Per-building day/size retention in `scripts/openfdd_data_retention_sidecar.sh` still needs `OPENFDD_RETENTION_SIDECAR_ENABLED=1`. It is operator tooling outside central.
