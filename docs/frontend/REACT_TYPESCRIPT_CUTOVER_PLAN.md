# React / TypeScript dashboard cutover plan

**Status:** Planning only — do not expand UI scope until PR #477 is on `master` and nightly GHCR is green.

## Current layout

| Path | Role |
| --- | --- |
| `workspace/dashboard/` | React 19 + TypeScript + Vite source |
| `frontend/` | Compiled static assets copied into Docker image |

Production serves **one** Rust edge image (API + static dashboard). No separate frontend container by default.

## Cutover phases

### Phase A — Build pipeline (done in Docker)

1. `npm ci && npm run build` in `workspace/dashboard`
2. Vite writes to `frontend/` (`VITE_OUT_DIR=../frontend` in Dockerfile)
3. Rust edge binary serves `FRONTEND_DIR=/app/frontend`

### Phase B — API wiring (in progress)

Wire dashboard to existing edge `/api/*` endpoints via Vite dev proxy and production same-origin fetch.

### Phase C — FDD engine UI (after engine on master)

Typed surfaces (no raw SQL editing in operator UI):

- 50-rule registry browser (from `sql_rules/registry.yaml`)
- Rule tuning panel (`control`-typed parameters per `SQL_RULE_TUNING_CONTRACT.md`)
- DataFusion run/preview (trigger `fdd_cli` or future edge API)
- Parquet/cache status
- Role mapping editor (physical column → logical role)
- Benchmark/validation results viewer

### Phase D — Optional enterprise layout (later)

Separate frontend container only for reverse-proxy / CDN deployments — not the default.

## Dev workflow

```powershell
# Terminal 1 — edge API
cargo run -p open_fdd_edge_prototype

# Terminal 2 — Vite dev server (proxies /api to :8080)
cd workspace/dashboard
npm ci
npm run dev
```

## Production workflow

Docker multi-stage build (see `Dockerfile` dashboard stage). No manual `frontend/` commit required in CI.

## References

- `docs/frontend/FRONTEND_BUILD_STRATEGY.md`
- `docs/frontend/API_CONTRACT.md`
- `docs/frontend/STATIC_SERVE_STRATEGY.md`
- `docs/migration/vibe19/DASHBOARD_UI_SPEC.md`
