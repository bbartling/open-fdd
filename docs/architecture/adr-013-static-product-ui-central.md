---
title: ADR — Static product UI served by central
parent: Architecture
nav_order: 13
nav_exclude: true
---

# ADR-013 — Static product UI served by central

- **Status:** Accepted (2026-11-01), Wave B shell
- **Supersedes (eventually):** delivery item 4 in [ADR-001](adr-001-react-rust-modernization.md) (`openfdd-web` nginx container as sole browser entry)
- **Does not change:** Timescale-only historian, SQL FDD math, JWT auth on `/api`, CSP direction (no `unsafe-inline` / `unsafe-eval` in product CSP)

## Context

Open-FDD 4.0 shipped the React SPA in `openfdd-web`; source moves to `archive/product-ui/react-spa-v4` while static UI becomes default on central. The NF Bench Viz reference demonstrates a dark, modular static shell that talks to same-origin APIs. Operators want that UX without Clerk/LAN auth, BACnet control, or secrets from the reference tree.

## Decision

1. **Wave B–F program:** Add a static product shell under `services/central/static/product/`, served by central when `OPENFDD_STATIC_PRODUCT_UI=1` (alias `OPENFDD_STATIC_UI`). Assets mount at `/app/`; `/api/*` remains the JSON API (unknown routes stay JSON 404).
2. **Session:** Browser stores JWT from `POST /api/auth/login` in `sessionStorage` and sends `Authorization: Bearer` on fetches — same contract as the React SPA.
3. **Design tokens:** background `#0b1020`, panels `#121a30` / `#18223d`, line `#24304f`, text `#e6ebf5`, muted `#8a96b3`, accent `#4cc9f0`, warm `#f8961e`, fault `#f94144`, cool `#4361ee`, healthy `#43aa8b`.
4. **Parity waves:** Model tree + SPARQL (C), charts/FDD tuners with vendored ECharts (C), schedule cards on durable jobs (D), CSV/admin/demo + guard replacement (E), then retire `openfdd-web` on a patch release with rollback image (F).
5. **Wave F (4.0.9+):** Default portal compose drops `openfdd-web`; central `/app/` is the product UI. React rollback uses `docker/compose.react.yml` and GHCR `openfdd-web` (rollback-only).

## Consequences

- Central image carries static assets (COPY to `/app/static/product`); default portal compose sets `OPENFDD_STATIC_PRODUCT_UI=1`.
- Qualification updates (ZAP, old-frontend soak) move to Wave E/F — not part of 4.0.8 publish cohort.
- Capability inventory and modular JS (`session`, `api`, page modules) grow in-repo; no copy of reference `.env`, lab IDs, or Windows-only tree.
