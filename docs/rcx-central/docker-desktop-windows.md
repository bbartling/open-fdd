# RCx Central on Docker Desktop (Windows)

## Prerequisites

- Docker Desktop for Windows
- Edge reachable from the host (e.g. Tailscale)

## Run

```powershell
cd open-fdd
docker compose -f docker/rcx-central/docker-compose.yml up --build
```

Open:

- Dash: http://localhost:8050
- API health: http://localhost:8060/health

No git clone required at runtime if you pull `ghcr.io/bbartling/openfdd-rcx-central` (when published). Build locally with `OPENFDD_IMAGE_TAG=local`.

## Volumes

| Volume | Purpose |
|--------|---------|
| `rcx-central-data` | Rollups, reports (`portfolio/data/reports/`) |
| `rcx-central-config` | `sites.json`, masked credentials |

## Tailscale networking

If Edge is reachable on the Windows host but not from inside the Linux container:

1. Test from host: `curl https://<tailscale-ip>:8765/health`
2. Test from container: `docker compose exec rcx-central-api curl -s http://<tailscale-ip>:8765/health`
3. If container cannot route, use the host's Tailscale IP (Docker Desktop often routes LAN correctly) or document `host.docker.internal` proxy for dev.

## Smoke test

```bash
./scripts/test_rcx_central_docker.sh
```

Windows PowerShell variant: run compose up, then curl health URLs manually per steps above.
