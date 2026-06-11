# Open-FDD cloud exporter sidecar

Generic sidecar that polls the bridge HTTP API and POSTs a JSON snapshot to a
webhook-compatible endpoint (PostBin, webhook.site, RequestBin, etc.).

**Disabled by default** — set `OPENFDD_EXPORT_DRY_RUN=0` and `OPENFDD_EXPORT_ENDPOINT`
only when you intend to forward data off-site.

## Example (dry-run)

```bash
export OPENFDD_BRIDGE_BASE_URL=http://127.0.0.1:8765
export OPENFDD_EXPORT_ENDPOINT=https://webhook.site/your-uuid
export OPENFDD_EXPORT_DRY_RUN=1
python -m cloud_exporter.app --once
```

## Docker Compose

Enable profile `cloud-export` in `docker/compose.edge.yml` (see docs/ops/cloud-exporter.md).

## Security

- Does not export operator passwords, auth env files, or raw secrets.
- Tokens are redacted in logs.
- Use dry-run to verify payload shape before enabling live POST.
