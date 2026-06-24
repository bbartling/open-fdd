# CSV export sidecar

CSV exports are **generated outputs** for Excel users, integrations, and archives. They are not canonical storage.

## Architecture

1. `scripts/openfdd_csv_export_sidecar.sh` runs on cron.
2. Authenticates to Open-FDD export APIs (`/api/export/*.csv`, BACnet override export).
3. Writes CSV to `OPENFDD_EXPORT_SIDECAR_OUTPUT_DIR`.
4. Rotates old files using `OPENFDD_EXPORT_SIDECAR_RETENTION_DAYS`.

The sidecar **never** reads Feather/Arrow files directly.

See [cron_setup.md](cron_setup.md) and [security.md](security.md).
