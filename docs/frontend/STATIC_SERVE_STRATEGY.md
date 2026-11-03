# UI serve strategy

> **Updated 2026-11.** Product UI is **Open-FDD Central** static assets at `/app/` on `openfdd-central`.

## Production (portal recipe)

Central serves the Bench Viz static shell when `OPENFDD_STATIC_PRODUCT_UI=1`
(default on `docker/compose.portal.yml` and `docker/compose.csv.yml`).

| Surface | Behavior |
| --- | --- |
| Product UI | `http://127.0.0.1:8080/app/` (same-origin `/api`) |
| Caddy (optional) | `OPENFDD_CADDY=1` on `portal` / `csv` → `docker/compose.caddy.central.yml` (`tls internal` by default) |
| API | Central on `:8080` (`/api/health`, JWT routes, FDD) |
| Docs / OpenAPI | Central on `:8080` (`/docs`, `/openapi.json`) |
| React rollback | `docker/compose.react.yml` + GHCR `openfdd-web` (see LOCAL_HOSTING) |

## Docker

Static assets live in `services/central/static/product/` and ship inside
`ghcr.io/bbartling/openfdd-central`. React rollback builds from
`archive/product-ui/react-spa-v4/Dockerfile` → `openfdd-web`.

## Verification

```bash
./scripts/openfdd_stack_up.sh portal
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/app/
```

## Security

- Do not expose Open-FDD to the public internet by default.
- CSP on `/app/*` is set by central (no CDN, no `unsafe-inline` / `unsafe-eval`).
