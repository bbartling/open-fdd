---
title: Open-FDD Central API
parent: Portfolio
nav_order: 2
---

# Open-FDD Central API

Multi-building desk over Tailscale/VPN. **Read-only toward edges** — no BACnet, no commands.

## Start

```bash
pip install -r portfolio/requirements.txt
cp portfolio/sites.json.example portfolio/sites.json   # edit base URLs
./scripts/run_central_api.sh                           # http://127.0.0.1:8060
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Central service health |
| GET | `/api/central/sites` | Edge registry + last check-in |
| POST | `/api/central/sites/{site_id}/collect-validate` | Portfolio collect + read-only validation |
| POST | `/api/central/validation/run` | One-off (`duration_hours=0`) or 24h plan |
| GET | `/api/central/validation/jobs` | Stored validation jobs |
| GET | `/api/central/validation/jobs/{id}` | Job detail + cycles |
| POST | `/api/central/rcx/report` | Download RCx `.docx` report |

## Validation plan body

```json
{
  "site_id": "acme",
  "interval_hours": 2,
  "duration_hours": 24,
  "sleep_seconds": 0
}
```

Set `sleep_seconds` to `7200` for true 2-hour wall-clock spacing. Use `duration_hours: 0` for a one-off probe.

## RCx report

POST `/api/central/rcx/report` with `{"site_id": "acme"}`. Includes:

- Active faults **with equipment name** (never severity-only)
- Fault-hour estimates from rollup history
- Missing-data / validation warnings

## Safety

Central never writes to BACnet devices or edge schedules. All edge calls use authenticated GET probes only.
