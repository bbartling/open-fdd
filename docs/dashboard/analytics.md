# Dashboard analytics (Haystack + DataFusion)

The Rust dashboard replaces SPARQL-only analytics with a Haystack model query layer, historian summaries, and DataFusion fault outputs.

## API routes (auth required)

| Route | Purpose |
|-------|---------|
| `GET /api/dashboard/summary` | Portfolio, model, sources, faults, historian, security |
| `GET /api/dashboard/analytics` | Trends, top faulted equipment, rule health |
| `GET /api/dashboard/model-coverage` | Equipment/point counts, mapped vs unmapped |
| `GET /api/dashboard/source-health` | Protocol enablement and coverage |
| `GET /api/dashboard/historian-health` | Row counts, latest sample |
| `GET /api/dashboard/security` | Auth + Caddy/TLS status |
| `GET /api/health/stack` | Stack health for React dashboard stream |
| `GET /api/faults/status` | Fault families for home dashboard |

Public: `GET /api/building/snapshot` (unauthenticated snapshot for login page).

## UI concepts

- **Equipment model** — Haystack equips from `GET /api/model/haystack`
- **Mapped / unmapped points** — from model query layer
- **Source coverage** — BACnet, Modbus, JSON API, CSV by protocol flags
- **Fault coverage** — active/confirmed/raw faults from DataFusion rules
- **BACnet overrides** — priority 8 and other counts when BACnet enabled

BRICK/SPARQL import remains optional legacy; it is not required for dashboard analytics.

See [modeling/haystack_dashboard_model.md](../modeling/haystack_dashboard_model.md).
