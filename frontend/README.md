# Frontend (React product UI)

**ADR:** [ADR-001 — React SPA and Python exit](../docs/architecture/adr-001-react-rust-modernization.md)

## Active SPA

Production React app: **[`web/`](web/)**

```bash
cd frontend/web
npm ci
npm run typecheck
npm run test
npm run build
```

- Same-origin `/api` against central (set `VITE_API_BASE` only if splitting origins).
- Advertise React path with `OPENFDD_REACT_UI=1` on central (`GET /api/capabilities` → `capabilities.react_ui`).

## Historical note

This directory was marked retired during Milestone A convergence. ADR-001
supersedes that lock. Do not introduce a Python/FastAPI sidecar for the SPA.
