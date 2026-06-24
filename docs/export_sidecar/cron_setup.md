# CSV export sidecar — cron setup

```bash
export OPENFDD_EXPORT_SIDECAR_OUTPUT_DIR=/data/openfdd/exports
export OPENFDD_EXPORT_SIDECAR_API_BASE=http://127.0.0.1:8080
export OPENFDD_EXPORT_SIDECAR_AUTH_TOKEN_FILE=/run/secrets/openfdd_export_token
export OPENFDD_EXPORT_LOOKBACK_HOURS=24
./scripts/openfdd_csv_export_sidecar.sh
```

Dry run: `OPENFDD_EXPORT_SIDECAR_DRY_RUN=1 ./scripts/openfdd_csv_export_sidecar.sh`
