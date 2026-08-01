# P2-M6 — Streamlit product removal

## Removed from product path

| surface | change |
|---|---|
| Default compose | `compose.central.yml` `ui` service → `profiles: [streamlit-legacy]` |
| Generation default on central compose | `OPENFDD_UI_GENERATION_DEFAULT=react` |
| Required CI product gates | Streamlit syntax/pytest greps removed; React + `ARCHIVED.md` required |
| AppSec dashboard guard | React package.json + archive marker |
| Release/GHCR validate | Archive marker instead of py_compile streamlit_app |

## Retained for recovery / oracle

- `services/ui/**` source + Dockerfile (historical GHCR `openfdd-ui` builds may continue for archive)
- `open_fdd/{rules,analytics,reporting,ecm_engineering}`
- `tools/react_parity/**`

## Last Streamlit product recovery

- Marker: `services/ui/ARCHIVED.md`
- Compose: `docker compose -f docker/compose.central.yml --profile streamlit-legacy up -d`
- Prefer pinning an immutable `ghcr.io/bbartling/openfdd-ui@sha256:…` from pre-removal retention

## Matrix updates

Product Streamlit entry disposition → **DELETED** from shipping topology (source archived in-tree).
Leaf twins (P2-DEL-01…06) remain in archive tree; not imported by product compose.
