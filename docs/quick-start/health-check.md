---
title: First login and health check
parent: Quick Start
nav_order: 2
---

# First login and health check

## Health endpoints

| URL | Auth | Meaning |
|-----|------|---------|
| `GET /health` | Public | Bridge process alive |
| `GET /health/stack` | Bearer token | Container traffic-light summary |

```bash
curl -s http://<host>:8765/health | jq .
# or through Caddy:
curl -s http://<host>/health | jq .
```

**Stack script** (from repo on control machine or edge):

```bash
./scripts/stack_health_check.sh <edge-ip-or-hostname>
```

## Login

1. Open the dashboard URL (Caddy `:80` → bridge `:8765`).
2. Sign in with credentials from `workspace/auth.env.local` (default roles: `integrator`, `operator`).
3. Confirm **Building insight** / home loads without API errors.

```bash
curl -s -X POST http://<host>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"integrator","password":"<from-auth-env>"}'
```

## Smoke checklist

| Check | Pass criteria |
|-------|----------------|
| Dashboard HTML | `200` on `/` |
| Auth | `POST /api/auth/login` returns token |
| Model | `GET /api/model/health` shows point count |
| BACnet | Commission container running; discover returns devices (if OT LAN attached) |
| Historian | Feather store growing under `workspace/data/feather_store/` |
| Rule Lab | Lint + test-rule APIs respond (integrator role) |

## Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| 401 on all routes | Set `auth.env.local`; disable `OFDD_AUTH_DISABLED` on LAN |
| Empty BACnet discover | Fix `BACNET_BIND` in `commission.env` — see [BACnet network setup](../bacnet/network-setup) |
| Caddy shows welcome page | Reload Caddy config pointing to bridge `:8765` |
| Stale UI after upgrade | Hard refresh; confirm new bridge image tag deployed |
