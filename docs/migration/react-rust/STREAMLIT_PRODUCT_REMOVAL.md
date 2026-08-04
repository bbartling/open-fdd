# Streamlit product — REMOVED

In-repo Streamlit / `openfdd-ui` / overview-oracle are **not** product surfaces.
Product UI is React (`frontend/web` → `openfdd-web`, `docker/compose.react.yml`).

## Removed from product path

| surface | change |
|---|---|
| Compose `ui:` services | Deleted from `compose.central.yml`, `compose.csv.yml`, `compose.standalone.yml` |
| `streamlit-legacy` profile | Gone — no Streamlit recovery compose |
| GHCR `openfdd-ui` | No longer built or published |
| Overview-oracle proxy | Removed from `frontend/web/nginx.conf` + `Caddyfile.react.http` |
| CI guards | Assert React present + `services/ui` absent |

## Retained (not product UI)

- `open_fdd/{rules,analytics,reporting,ecm_engineering}` (offline / ECM tooling)
- `tools/wattlab_export/` (WattLab exporter relocated off `services/ui`)
- Vibe 19 / Vibe 20 as **external** companions only

## Matrix

Product Streamlit disposition → **REMOVED** (tree delete follows CI/compose scrub).
