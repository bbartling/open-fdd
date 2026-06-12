---
title: OpenFDD RCx Central API
parent: Portfolio
nav_order: 2
---

# OpenFDD RCx Central API

Local analyst API for multi-edge RCx workflows over Tailscale/VPN. **Read-only toward OpenFDD Edge** — no BACnet, no commands.

> Package path: `portfolio/central/api.py` — service name **openfdd-rcx-central**.

## Start

```bash
pip install -r portfolio/requirements.txt
./scripts/run_central_api.sh   # http://127.0.0.1:8060/health
```

Docker Desktop: [docs/rcx-central/docker-desktop-windows.md](../rcx-central/docker-desktop-windows.md)

## Edge registry (browser auth)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/central/edges` | Saved Edge instances (secrets masked) |
| POST | `/api/central/edges` | Add/update Edge |
| POST | `/api/central/edges/test` | Test connection (health + model) |
| PUT | `/api/central/edges/{site_id}` | Update Edge |
| DELETE | `/api/central/edges/{site_id}` | Remove Edge |

## Analytics & RCx

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/central/mechanical-summary/{site_id}` | Equipment counts, BACnet, readiness |
| GET | `/api/central/fdd-analytics/{site_id}` | FDD rules + chart packs |
| POST | `/api/central/rcx/preview` | Data readiness + chart catalog |
| POST | `/api/central/rcx/charts/preview` | Matplotlib PNG previews (base64) |
| POST | `/api/central/rcx/report` | Download DOCX report |

## Validation (legacy collect workflow)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/central/sites` | Edge registry + last check-in |
| POST | `/api/central/sites/{site_id}/collect-validate` | Collect rollup + validation |
| POST | `/api/central/validation/run` | One-off or scheduled plan |
| GET | `/api/central/validation/jobs` | Stored jobs |
| GET | `/api/central/validation/jobs/{id}` | Job detail |

## RCx report body

```json
{
  "site_id": "acme",
  "hours": 24,
  "charts": ["fault_hours_by_severity", "ahu_sat_vs_setpoint"],
  "sections": ["executive_summary", "mechanical_summary"],
  "save_to_volume": true
}
```

Reports save under `portfolio/data/reports/` (configurable via `OPENFDD_RCX_CENTRAL_DATA`).

Legacy endpoint: `POST /api/central/rcx/report-legacy`
