# Edge authentication (RCx Central)

## Browser flow

1. Open RCx Central → **Edge Connections**
2. Enter site_id, name, Edge base URL (`https://<tailscale-ip>:8765`)
3. Enter username/password (or bearer token via API)
4. **Test Connection** — probes `/health`, `/api/model/health`, `/api/faults/status`
5. **Save Edge** — writes to `portfolio/config/sites.json` + `credentials.json` (Docker volume)

## API

```text
GET  /api/central/edges
POST /api/central/edges
POST /api/central/edges/test
PUT  /api/central/edges/{site_id}
DELETE /api/central/edges/{site_id}
```

Secrets are **never** returned in API responses or committed to git. Passwords are masked in UI after save.

## Auth types

- `password` — `POST /api/auth/login` on Edge
- `bearer` — static token in credentials store
- `none` — public Edge endpoints only (dev)

## Rejected URLs

`file://`, `ftp://`, and hosts without scheme are rejected.
