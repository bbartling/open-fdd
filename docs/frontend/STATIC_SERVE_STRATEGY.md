# UI serve strategy

> **Updated 2026-07-27.** Product UI is Streamlit (`services/ui`), not a Vite/Caddy SPA.

## Production

The UI is served by the `openfdd-ui` container: Streamlit from `services/ui`,
listening on **:8501** in-container (published as **:3000**). Central owns the
API on **:8080**. The UI calls central over the compose network (or host
`localhost` in local dev) — it is not a static SPA with a same-origin Caddy
proxy.

| Surface | Behavior |
| --- | --- |
| UI browser | Streamlit on `:3000` (host) → `:8501` (container) |
| API | Central on `:8080` (`/api/health`, JWT routes, FDD) |
| Docs / OpenAPI | Served by central on `:8080` |

## Docker

`services/ui/Dockerfile` builds the Streamlit image from the open-fdd repo
(Python + `open-fdd[oracle]` + app code). Image:
`ghcr.io/bbartling/openfdd-ui:${OPENFDD_IMAGE_TAG:-nightly}`.

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
