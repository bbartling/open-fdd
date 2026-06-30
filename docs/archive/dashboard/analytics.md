# Dashboard analytics

Home and portfolio views combine **SPARQL-backed model coverage**, historian health, and DataFusion fault output.

## Routes

| Route | Auth | Purpose |
|-------|------|---------|
| `GET /api/dashboard/summary` | JWT | Portfolio rollup |
| `GET /api/dashboard/analytics` | JWT | Trends and rule health |
| `GET /api/dashboard/model-coverage` | JWT | Equipment/point counts, mapped vs unmapped |
| `GET /api/dashboard/source-health` | JWT | Protocol coverage |
| `GET /api/dashboard/historian-health` | JWT | Sample freshness |
| `GET /api/dashboard/security` | JWT | Auth and TLS status |
| `GET /api/building/status` | none | Public HVAC summary (feeds, rules, faults) |
| `GET /api/faults/status` | JWT | Fault families |

Model counts are computed via SPARQL over the Haystack RDF projection — not client-side grid filtering. See [modeling/haystack_dashboard_model.md](../modeling/haystack_dashboard_model.md).
