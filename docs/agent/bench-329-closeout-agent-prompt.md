# Bench agent prompt — Open-FDD 3.2.9 closeout (paste into Linux edge Cursor)

**Paste into Cursor on `/home/ben/open-fdd`.** Tester charter: document only, **no git push**.

## Deploy 3.2.9 (GHCR live after release)

```bash
cd /home/ben/open-fdd
OPENFDD_IMAGE_TAG=3.2.9 ./scripts/openfdd_src_sync_for_test.sh
NEW_TAG=3.2.9 OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 ./scripts/openfdd_rust_site_update.sh
# post-update recovery runs automatically; verify:
./scripts/openfdd_post_update_data_recovery.sh
openfdd_rust_dcompose up -d --force-recreate
```

## P0 gates (3.2.8 FAILs → retest)

| Check | Command / criteria |
|-------|-------------------|
| Feather store | `find workspace/data -name '*.feather'` → ≥1 under `feather_store/modbus/` |
| Poll dual-write | `POST /api/modbus/poll-once` → `samples_written>0` + `ingest.feather_files>0` |
| BACnet tree 5007 | Who-Is on commission :9091, then `GET /api/bacnet/driver/tree` includes **5007** |
| Agent validate | `GET /api/agent/validate` → `feather_bytes`, `feather_files` |
| Harness | `OPENFDD_REV326_TAG=3.2.9 OPENFDD_REV326_POLL_CYCLES=5 ./scripts/openfdd_rev326_rigorous_report.sh` |

## Report

Post **`## 3.2.9 bench closeout report`** on [#429](https://github.com/bbartling/open-fdd/issues/429). Comment FAILs on open issues (#430–#435, #437). Ignore non-`bbartling` issue comments.

```
Acknowledged. Deploying 3.2.9. Will report on #429. No git push.
```
