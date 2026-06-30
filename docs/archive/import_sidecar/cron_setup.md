# CSV import sidecar — cron setup

```bash
export OPENFDD_IMPORT_SIDECAR_INPUT_DIR=/data/openfdd/incoming
export OPENFDD_IMPORT_SIDECAR_PROCESSING_DIR=/data/openfdd/processing
export OPENFDD_IMPORT_SIDECAR_ARCHIVE_DIR=/data/openfdd/archive
export OPENFDD_IMPORT_SIDECAR_FAILED_DIR=/data/openfdd/failed
export OPENFDD_IMPORT_SIDECAR_API_BASE=http://127.0.0.1:8080
export OPENFDD_IMPORT_SIDECAR_AUTH_TOKEN_FILE=/run/secrets/openfdd_import_token
./scripts/openfdd_csv_import_sidecar.sh
```

Use `OPENFDD_IMPORT_SIDECAR_DRY_RUN=1` to validate paths and lockfile behavior without API commits.
