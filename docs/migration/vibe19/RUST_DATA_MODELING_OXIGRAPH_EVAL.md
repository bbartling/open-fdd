# Rust data modeling — Oxigraph evaluation

Evaluation of whether Haystack RDF / SPARQL modeling should move to Rust (Oxigraph) in vibe19.

## Current Python modules

| Module | Role | Request-path hot? |
| --- | --- | --- |
| `haystack_rdf/csv_bootstrap.py` | Build TTL/model from CSV tree | No — bootstrap only |
| `haystack_rdf/model_store.py` | Persist `model.json` / TTL | No — startup / manual |
| `haystack_rdf/model_sparql.py` | SPARQL over in-memory graph | **Sometimes** — model queries |
| `haystack_rdf/resolver.py` | `column_for_role(equipment, role)` | **Yes** — every cookbook page load |
| `haystack_rdf/feather_cache.py` | Historian load cache | **Yes** — every page |
| `haystack_rdf/fastapi_routes.py` | `/api/rdf/bootstrap`, model API | Occasional |
| `haystack_rdf/csv_discovery.py` | Filesystem equipment discovery | **Yes** — preferred over SPARQL |

## Findings

1. **SPARQL is not the primary historian loader** — filesystem paths (`history_wide.csv`, `columns.csv`) drive data access.
2. **SPARQL/resolver is on the critical path** for mapping logical roles → physical columns when `columns.csv` is incomplete.
3. **Model discovery is cacheable** — `model.json` + feather/parquet sidecars already avoid repeated CSV parsing.
4. **Oxigraph would help** if we need faster bootstrap validation, offline model lint, or embedded SPARQL without Python GIL — not for Plotly chart generation.

## Recommendation (stage 1)

| Action | Priority |
| --- | --- |
| Cache resolver output per `(building_id, equipment_id)` to JSON | P0 — Python |
| Expand Rust `columns.csv` role map to match `ROLE_CANDIDATES` | P0 — Rust |
| Avoid SPARQL per HTTP request | Policy |
| Oxigraph in Rust for bootstrap lint / CI validate | P2 — optional crate `fdd_model` |
| Full RDF port | **Defer** — semantics must stay Haystack/Open-FDD compatible |

## What should remain Python (for now)

- TTL generation / commissioning bundles (`commissioning_bundle.py`)
- FastAPI RDF admin routes
- Interactive model editor (`data_model.html`)

## Rust integration point

`fdd_core::validate_building()` + `load_column_role_map()` are the first Rust hooks. Next: emit a `resolved_roles.json` sidecar during ingest that Python oracle and SQL share.
