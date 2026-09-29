# Local data budget (100 GiB, oldest first)

Default cap for **local / edge** historian parquet plus analytics result parquet is **100 GiB** (`OPENFDD_LOCAL_DATA_BUDGET_GIB`). Past the cap, delete the oldest parts and keep the newest. One newest file that is itself larger than the cap is kept.

This is separate from the per-building historian limit (365 days or 5 GiB, `OPENFDD_HISTORIAN_SIZE_GIB`). The 100 GiB figure is the hub/local pool.

## What is counted

Under the parquet root:

- `history/**/*.parquet`
- `analytics_results/**/*.parquet`
- `building=*/*.parquet`
- `tenants/{id}/history` and `tenants/{id}/analytics_results`

Not counted: `backups/` and `archives/` (operator off-box copies stay).

Order key: `part-YYYYMMDDTHHMMSSZ`, else `year=`/`month=` (first of that month), else file mtime.

## Railway

`RAILWAY_ENVIRONMENT` set and `OPENFDD_DATA_BUDGET_ENABLED` **unset** → eviction stays **off**. Railway volume policy is unchanged. Set `OPENFDD_DATA_BUDGET_ENABLED=1` only when an operator wants this cap on that volume.

## API

Hub admin:

- `GET /api/data-management/budget` — used bytes, over-budget bytes, would-drop counts. Does not delete.
- `POST /api/data-management/retention/apply` with `{ "confirm": "APPLY DATA BUDGET" }` — runs eviction when the budget is enabled.

## Update preflight

Reserved free space defaults to **10%** of the disk (`OPENFDD_DISK_RESERVED_FREE_PERCENT`, clamp 1–50). An on-box backup is the size of a second copy of live parquet. A ~200 GiB host with a 100 GiB live set does **not** have room for that copy plus the reserve. Skip the full copy or prune oldest parts until the copy fits. If free space stays under the reserve even after that reclaim, fail closed and do not start the update.

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

Eviction walks hive trees (`history/`, `analytics_results/`, exact key `building={id}`, tenant history). It does not substring-match `equipment_id`. `building_id` stays a path parameter.

## Soft-OPEN

Logic and tests ship here. Proof on a real edge disk (live cap, prune, update with and without headroom) is a field pass, not this change. Do not delete operator archives to make a lab green. No VERSION bump. Not an FQ claim. Scorecard: [ANALYTICS_RESULT_CACHE.md](ANALYTICS_RESULT_CACHE.md) § Compliance.

Per-building day/size retention in `scripts/openfdd_data_retention_sidecar.sh` still needs `OPENFDD_RETENTION_SIDECAR_ENABLED=1`. The 100 GiB pool does not replace that sidecar.
