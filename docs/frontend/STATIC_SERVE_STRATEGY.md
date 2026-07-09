# Static serve strategy

## Production

Rust edge binary (`open_fdd_edge_prototype`) serves compiled dashboard from `FRONTEND_DIR` (default `/app/frontend` in Docker).

| Route | Behavior |
| --- | --- |
| `/api/*` | JSON API handlers |
| `/assets/*` | Static JS/CSS from Vite build |
| `/` | `index.html` |
| Other non-API paths | SPA fallback → `index.html` |

## Docker

`Dockerfile` stages:

1. **dashboard** — Node 22 builds `workspace/dashboard` → `/app/frontend`
2. **builder** — Rust release binaries
3. **runtime** — copies `frontend/` + binaries; `HEALTHCHECK` hits `/api/health`

## Verification

```powershell
docker build -t openfdd-edge-rust:ci .
docker run -d --name openfdd-smoke -p 8080:8080 openfdd-edge-rust:ci
curl.exe -fsS http://127.0.0.1:8080/api/health
curl.exe -fsS http://127.0.0.1:8080/
docker rm -f openfdd-smoke
```

## Security

- Do not expose Open-FDD to the public internet by default.
- Use auth env (`OFDD_AUTH_REQUIRED`) and local/private networks for edge deployments.
