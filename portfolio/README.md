# OpenFDD RCx Central

**Local analyst / RCx engineer tool** — multi-edge analytics, matplotlib chart preview, and DOCX reports. Runs on an analyst workstation or **Docker Desktop**; **not** deployed on the OT edge by default.

> Internal package path remains `portfolio/` for import stability.

| Product | Where it runs |
|---------|----------------|
| **OpenFDD Edge** | Building OT LAN — Arrow-native FDD, BACnet, read-only APIs |
| **OpenFDD RCx Central** | Analyst PC / Docker — queries Edge over Tailscale/VPN |

| Path | Role |
|------|------|
| `sites.json` / `config/sites.json` | Edge registry (URL; credentials in `config/credentials.json`) |
| `collector/` | Poll `GET /api/building/portfolio-rollup` per site |
| `central/` | FastAPI API — edges, mechanical summary, RCx preview/report |
| `dash/app.py` | Dash UI (`:8050`) — **OpenFDD RCx Central** |
| `data/` | Runtime CSV, rollups, generated reports (gitignored) |
| `config/` | Browser-saved edges + secrets (gitignored) |

## Commands (host)

```bash
pip install -r portfolio/requirements.txt
./scripts/run_central_api.sh    # http://127.0.0.1:8060/health
./scripts/run_portfolio_dash.sh # http://127.0.0.1:8050
python3 scripts/portfolio_collect.py
```

## Docker Desktop

```bash
./scripts/run_rcx_central_docker.sh
```

Docs: [docs/rcx-central/index.md](../docs/rcx-central/index.md)

## Safety

RCx Central is **read-only** toward OpenFDD Edge and BACnet.
