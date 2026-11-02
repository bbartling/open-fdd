# Product UI — archived React SPA

The React portal UI (`openfdd-web`) moved off the active product tree. **Default operator UI** is the static Bench Viz shell on central (`/app/`, [ADR-013](../../docs/architecture/adr-013-static-product-ui-central.md)). This tree remains for rollback builds and historical reference.

| Path | Was |
| --- | --- |
| [`react-spa-v4/`](react-spa-v4/) | `frontend/web` — React + TypeScript SPA, nginx image `ghcr.io/bbartling/openfdd-web` |

- **Not** under `archive/ot-edge/` (OT wire / fieldbus only).
- CI may still build `openfdd-web` from `react-spa-v4/Dockerfile` until portal compose drops the web service (Wave F).
- Do not copy secrets, lab IDs, or `.env` from operator checkouts into this tree.

## Rollback

Pin the last known-good `openfdd-web` `sha-*` from `./scripts/ghcr_newest_by_created.py openfdd-web` and set `OPENFDD_WEB_IMAGE` in the gitignored repo-root `.env`. Static UI rollback: disable `OPENFDD_STATIC_PRODUCT_UI` and use the React container on host `:3000`.
