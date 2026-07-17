# Static serve strategy

## Production

The UI is served by the `openfdd-ui` container: a Caddy image that hosts the
compiled Vite dashboard from `/srv` and proxies API traffic to `central`. The
UI listens on `:80` in-container (published as `:3000`) and central owns the
API on `:8080`.

| Route | Behavior |
| --- | --- |
| `/api*` | `reverse_proxy central:8080` |
| `/docs*`, `/openapi.json` | `reverse_proxy central:8080` |
| `/` and other paths | static `/srv`, SPA fallback → `index.html` |

Same-origin API means remote LAN browsers hit the UI on `:3000` and the proxy
forwards `/api` to central — no CORS or separate API host needed.

## Docker

`workspace/dashboard/Dockerfile` stages:

1. **build** — Node 22 builds `workspace/dashboard` → `/src/dist`
2. **runtime** — `caddy:2-alpine`, copies `dist` → `/srv` and
   `Caddyfile.ui` → `/etc/caddy/Caddyfile`

Image: `ghcr.io/bbartling/openfdd-ui:${OPENFDD_IMAGE_TAG:-nightly}`.

## Verification

```bash
./scripts/openfdd_stack_up.sh standalone
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:3000/          # UI index
curl -fsS http://127.0.0.1:3000/api/health # proxied to central
```

## Security

- Do not expose Open-FDD to the public internet by default.
- Set `OPENFDD_JWT_SECRET` (+ `OPENFDD_ADMIN_PASSWORD`) for auth and keep the
  stack on local/private networks for edge deployments.
