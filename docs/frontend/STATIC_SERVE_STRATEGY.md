# UI serve strategy

> **Updated 2026-07-27.** Product UI is React SPA (`frontend/web`), not a Vite/Caddy SPA.

## Production

The UI is served by the `openfdd-web` container: React from `frontend/web`,
listening on **:8080** in-container (published as **:3000**). Central owns the
API on **:8080**. The UI calls central over the compose network (or host
`localhost` in local dev). Optional Caddy fronts the LAN on **:80**.

| Surface | Behavior |
| --- | --- |
| UI browser | React on `:3000` (host) → `:8080` (container nginx) |
| UI via Caddy (optional) | `http://<host>/` → `web:8080` (`OPENFDD_CADDY=1` / `compose.caddy.react.yml`) |
| API | Central on `:8080` (`/api/health`, JWT routes, FDD) |
| API via Caddy | `http://<host>/api*` → `central:8080` |
| Docs / OpenAPI | Served by central on `:8080` |

## Docker

`frontend/web/Dockerfile` builds the React image from the open-fdd repo
(Python + `open-fdd[oracle]` + app code). Image:
`ghcr.io/bbartling/openfdd-web`.

Historical Vite/Caddy SPA notes and cutover plans live under
`docs/frontend/REACT_TYPESCRIPT_CUTOVER_PLAN.md` (obsolete) and
`docs/archive/deployment/`.

## Verification

```bash
./scripts/openfdd_stack_up.sh standalone
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

## Security

- Do not expose Open-FDD to the public internet by default.
- Set `OPENFDD_JWT_SECRET` (+ `OPENFDD_ADMIN_PASSWORD`) for auth and keep the
  stack on local/private networks for edge deployments.
