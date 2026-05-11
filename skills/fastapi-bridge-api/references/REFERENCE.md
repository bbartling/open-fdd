# FastAPI bridge — reference

Legacy monolith: `open_fdd/gateway/server.py` (retired). Representative routes:

| Tag | Methods | Paths |
|-----|---------|-------|
| health | GET | `/health` |
| sites | GET, POST, DELETE | `/sites`, `/sites/{site_id}`, `/sites/{site_id}/rule-pack` |
| model | GET, POST | `/model/export`, `/model/import`, `/model/validate`, `/model/ttl/sync`, `/model/ttl/status` |
| ingest | POST | `/ingest/csv`, `/ingest/csv/upload`, `/ingest/weather`, `/ingest/bacnet`, `/ml/train` |
| rules | GET, POST, PUT, DELETE | `/rules`, `/rules/{filename}`, `/rules/run`, `/rules/defaults`, `/rules/sync-definitions` |
| timeseries | GET, POST | `/timeseries/query`, `/timeseries/bounds`, `/timeseries/clean-metrics`, `/storage/timeseries/stats`, `/storage/timeseries/purge` |
| plots | GET, POST | `/plots/frame`, `/plots/site-frame`, `/plots/fdd-frame`, `/plots/share`, `/plots/share/{share_id}` |
| config | GET, POST | `/config/weather`, `/config/bacnet`, `/config/drivers/health`, `/config/drivers/export`, `/config/drivers/validate` |
| assistant | GET, POST | `/assistant/readiness`, `/assistant/ai-health`, `/assistant/apply-site-profiles` |
| sparql | GET, POST | `/data-model/sparql`, `/data-model/testing/query`, `/data-model/ttl` |
| openfdd-agent | GET, POST | `/openfdd-agent/context`, `/openfdd-agent/chat`, `/local-codex/diagnostics` |

Env: `OFDD_BRIDGE_URL`, `OFDD_BRIDGE_HOST`, `OFDD_DESKTOP_DATA_DIR`, `OFDD_CORS_ALLOW_PRIVATE_LAN`.

CLI (retired): `open-fdd-gateway`, `open-fdd-desktop-bridge`.
