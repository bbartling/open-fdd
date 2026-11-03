# UI serve strategy

> **Updated 2026-11.** Product UI is **Open-FDD Central** static assets at `/app/` on `openfdd-central`.

## Production (portal / csv)

Central serves the Bench Viz static shell when `OPENFDD_STATIC_PRODUCT_UI=1`
(default on `docker/compose.portal.yml` and `docker/compose.csv.yml`).

| Surface | Behavior |
| --- | --- |
| UI browser | `http://<host>:8080/app/` (central static product tree) |
| UI via Caddy (optional) | `OPENFDD_CADDY=1` → `docker/compose.caddy.central.yml` — HTTPS `tls internal`, HTTP → HTTPS redirect; reverse proxy to `central:8080` |
| API | Same origin on central `:8080` (`/api/*`, JWT routes, FDD) |
| Docs / OpenAPI | Central on `:8080` (`/docs`, `/openapi.json`) |

Caddy does **not** replace central security headers or CSP.

## React rollback

`docker/compose.react.yml` + GHCR `openfdd-web` publishes host `:3000` → container nginx `:8080`.
Use the same `OPENFDD_IMAGE_TAG` pin on `OPENFDD_WEB_IMAGE` when pulling rollback images.

## Verification

```bash
./scripts/openfdd_stack_up.sh portal --no-pull
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/app/
```

## Security

- Do not expose Open-FDD to the public internet by default.
- Set `OPENFDD_JWT_SECRET` (+ `OPENFDD_ADMIN_PASSWORD`) for auth and keep the
  stack on local/private networks for edge deployments.
