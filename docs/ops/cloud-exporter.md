# Cloud exporter sidecar

Optional `openfdd-cloud-exporter` container polls the bridge API and POSTs JSON to a
webhook-compatible URL (PostBin, webhook.site, etc.).

## Enable (edge compose)

```bash
export OPENFDD_EXPORT_ENDPOINT=https://webhook.site/your-uuid
export OPENFDD_EXPORT_DRY_RUN=1
docker compose --profile cloud-export up -d cloud-exporter
```

Set `OPENFDD_EXPORT_DRY_RUN=0` only when you intend live export.

## Security

- Disabled by default (`OPENFDD_EXPORT_DRY_RUN=1`).
- Does not export operator passwords or auth env files.
- Tokens are redacted in logs.

See `workspace/cloud_exporter/README.md` for environment variables.
