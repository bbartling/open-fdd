# Open-FDD React Web UI (`openfdd-web`)

Supported **product** UI after Phase 2 exit / Vibe 21 P1 recovery. Built as a
non-root Nginx image that proxies same-origin `/api` to central.

Streamlit (`openfdd-ui`) is **archived oracle only** — not this image.

## Development

```bash
npm ci
npm run dev
```

Vite defaults to `:5173`. Proxy `/api` to central via `vite.config.ts` or set
`VITE_API_BASE`.

## Production image (P1-M1)

```bash
docker build \
  --build-arg OPENFDD_GIT_SHA="$(git rev-parse HEAD)" \
  --build-arg OPENFDD_WEB_VERSION=0.1.0 \
  -t openfdd-web:local \
  -f frontend/web/Dockerfile \
  frontend/web

OPENFDD_WEB_IMAGE=openfdd-web:local ./scripts/release/smoke_react_web_image.sh
```

Compose recipe `react` / `react-ot` maps host `:3000` → container `:8080`
(nginx-unprivileged). Exposes `/version.json` (no-cache) and immutable `/assets/*`.

GHCR publishes `ghcr.io/bbartling/openfdd-web:sha-<7>` and `:nightly` from the
stack workflow.

## Environment

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE` | Optional API origin for Vite-only dev. Default same-origin. |
| `OPENFDD_REACT_UI` | Central capability flag (compose sets `1` for react recipes). |

## Scripts

| Script | Purpose |
| --- | --- |
| `npm run build` | `tsc -b && vite build` |
| `npm run test` | Vitest |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | ESLint (P1-M2-A) — fails CI on errors |
| `npm run test:e2e` | Playwright real-stack smoke (`e2e/`); skips if SPA down |
