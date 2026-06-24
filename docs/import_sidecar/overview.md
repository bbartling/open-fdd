# CSV import sidecar

Bulk CSV files are **transient inputs**. After commit, **Arrow/Feather is canonical**.

## Architecture

1. Files arrive in a watched host directory (`OPENFDD_IMPORT_SIDECAR_INPUT_DIR`).
2. `scripts/openfdd_csv_import_sidecar.sh` runs on cron or as a Docker profile.
3. The sidecar authenticates and calls the backend import API only:
   - `POST /api/import/jobs`
   - `POST /api/import/jobs/:job_id/upload`
   - `GET /api/import/jobs/:job_id/preview`
   - `POST /api/import/jobs/:job_id/commit`
4. Successful files move to archive (or delete when configured). Failures move to `failed/`.

The sidecar **never** parses business CSV logic in bash beyond orchestration and **never** writes Feather directly.

## Example cron

```bash
*/15 * * * * OPENFDD_IMPORT_SIDECAR_PROFILE=default_csv_import /opt/open-fdd/scripts/openfdd_csv_import_sidecar.sh >> /var/log/openfdd_csv_import_sidecar.log 2>&1
```

## Profiles

Copy `examples/import-profiles/csv_import.example.toml` to a gitignored local profile under `workspace/import-profiles/local/`.

See [cron_setup.md](cron_setup.md), [security.md](security.md).
