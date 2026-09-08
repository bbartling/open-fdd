# Capability matrix stub — Wave J Stage A (2026-09-08)

Machine-readable companion: evidence for J4/J6. Not a pass/fail gate by itself.

| Surface | Entry | Engine | Provenance note |
|---------|-------|--------|-----------------|
| FDD Run Rules | `POST /api/fdd/run` | `datafusion` | `sql_rules/` + `crates/fdd_rules` |
| Overview / RCx analytics | `POST /api/analytics/*` | `datafusion` and/or `central-analytics-v1` | `services/central/src/analytics/` — label alone ≠ soak pass |
| Export / packages | central export APIs | Rust I/O | No Python in product path |
| React SPA | `frontend/web/src/` | n/a (render) | No local FDD recompute |
| PyPI cookbook | `open_fdd.rules` | pandas | External oracle only |

**J4 triage (tip sample):** no product Python in central/web images found in Stage A inventory → prefer waive with evidence unless J5 image smoke finds otherwise.
