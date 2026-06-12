---
title: First login and health check
parent: Quick Start
nav_order: 2
---

# First login and health check

Quick checks after `docker compose up -d` on the edge host. Services use `restart: unless-stopped` — after a reboot, run `docker compose ps` once Docker is up (see [Run with Docker]({{ "/quick-start/docker/" | relative_url }}#survive-power-cycles)).

## Public health

```bash
curl -s http://127.0.0.1:8765/health
```

Through Caddy on port 80:

```bash
curl -s http://127.0.0.1/health
```

Expect `"ok": true` and `"auth_required": true` when auth is configured.

## Login

1. Open the dashboard (`http://<host-lan-ip>/` or `:8765`).
2. Sign in with credentials from `workspace/auth.env.local`.

```bash
curl -s -X POST http://127.0.0.1:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"integrator","password":"<from-auth-env>"}'
```

## Smoke checklist

| Check | Pass |
|-------|------|
| `docker compose ps` | bridge, commission, mcp-rag **Up** |
| `GET /health` | `200`, `ok: true` |
| Login | Token returned |
| BACnet poll | `samples.csv` growing (`tail -1 workspace/bacnet/polls/samples.csv`) |
| Historian | Files under `workspace/data/feather_store/` |

## Stack detail (authenticated)

Integrator token required:

```bash
TOKEN=$(curl -sf -X POST http://127.0.0.1:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"integrator","password":"..."}' | jq -r .token)
curl -sf http://127.0.0.1:8765/health/stack -H "Authorization: Bearer $TOKEN" | jq .
```

Look for `bacnet_poll` green/yellow in the services list.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 401 everywhere | Configure `workspace/auth.env.local` |
| Empty BACnet discover | Fix `BACNET_BIND` in `commission.env` — [network setup]({{ "/bacnet/network-setup/" | relative_url }}) |
| No poll rows | Commission container running? `points.csv` has enabled rows? |
| LAN browser timeout | Open firewall port 80 or 8765 |

Advanced probes (model graph, Rule Lab, compose profiles): [Developer health check]({{ "/developer/health-check/" | relative_url }}).
