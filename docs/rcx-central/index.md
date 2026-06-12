# OpenFDD RCx Central

**OpenFDD RCx Central** is the local analyst / RCx engineer dashboard. It runs on an analyst workstation or **Docker Desktop (Windows/Linux)** — not on the OT edge by default.

| Product | Role |
|---------|------|
| **OpenFDD Edge** | Arrow-native, no-pandas OT-LAN FDD machine at the building |
| **OpenFDD RCx Central** | Read-only multi-edge analytics, chart preview, DOCX reports |

Internal source path: `portfolio/` (package name unchanged).

## Quick start (host Python)

```bash
pip install -r portfolio/requirements.txt
./scripts/run_central_api.sh   # :8060
./scripts/run_portfolio_dash.sh # :8050
```

## Docker Desktop

```bash
./scripts/run_rcx_central_docker.sh
# Dash http://localhost:8050  API http://localhost:8060/health
```

See [docker-desktop-windows.md](docker-desktop-windows.md).

## Pages

- Overview — collected rollup trends (Plotly, light/dark theme)
- Edge Connections — add/test/save Edge URLs (secrets in local volume)
- Mechanical Summary — BRICK equipment counts from Edge APIs
- FDD Rules & Analytics — configured rules, chart packs
- Trend Explorer — pointer to Overview Plotly charts (local collect CSVs)
- RCx Report Builder — matplotlib preview, fault overlays, DOCX download
- Validation Runs — one-off read-only Edge probes
- Settings — API URL and volume paths

Model query details: [model-queries.md](model-queries.md)

## Safety

RCx Central is **read-only** toward Edge and BACnet. No writes, commands, or setpoint changes.
