# Open-FDD React Web UI

Minimal Vite + React + TypeScript SPA for the Open-FDD Phase 1 React parity program (P1-M2-02).

## Development

```bash
npm install
npm run dev
```

Vite dev server runs on port 5173 by default. Proxy `/api` to central in `vite.config.ts` when needed, or run central on the same origin.

## Environment

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE` | Optional API origin prefix. Default `''` (same-origin). Set to e.g. `http://localhost:8080` when the API runs on a different host during local dev. |
| `OPENFDD_REACT_UI` | **Server-side** (central). Set to `1` to advertise `capabilities.react_ui: true` on `GET /api/capabilities`. Default off — Streamlit remains the default Phase 1 UI. |

### Same-origin `/api`

In production, central (or compose) serves the built static assets and routes `/api/*` to the Rust backend on the same host. The React client uses relative paths (`/api/capabilities`, `/api/jobs`, …) so no CORS configuration is required when `VITE_API_BASE` is unset.

When developing with Vite on `:5173` and central on `:8080`, either:

- set `VITE_API_BASE=http://localhost:8080`, or
- add a Vite dev proxy for `/api`.

## Scripts

| Script | Description |
| --- | --- |
| `npm run dev` | Vite dev server |
| `npm run build` | Typecheck + production bundle → `dist/` |
| `npm run preview` | Serve production build locally |
| `npm run test` | Vitest unit tests |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | Placeholder (no ESLint config yet) |

## Docker

Build a static nginx image:

```bash
docker build -t openfdd-web .
docker run --rm -p 8081:80 openfdd-web
```

The container serves SPA assets only. Wire `/api` through central or a reverse proxy in compose.

## Contract

API types in `src/api/contract.ts` mirror `openfdd.api.contract.v1` (see `services/central/src/contract.rs`). Error responses use the envelope:

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "retryable": false,
    "request_id": "..."
  }
}
```

The fetch client in `src/api/client.ts` sends `x-request-id` on every request and parses this envelope on failure.

## Copy into open-fdd

This scaffold is intended to land at `frontend/web/` in the open-fdd repository:

```bash
rsync -av --exclude node_modules /tmp/openfdd-web/ ~/open-fdd/frontend/web/
```
