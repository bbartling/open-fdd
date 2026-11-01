# Static UI capability inventory (Wave B baseline)

Successor program: [ADR-013](../architecture/adr-013-static-product-ui-central.md). Reference UX only (NF Bench Viz static app); product code lives under `services/central/static/product/`.

| Surface | React SPA today | Static wave | API / notes |
| --- | --- | --- | --- |
| Auth | `/auth` | `/app/` login gate + Bench Viz header | `POST /api/auth/login`, JWT in `sessionStorage` |
| Overview health | Overview tab | Dashboard card (Wave B) | `GET /api/health` |
| Capabilities | Sidebar / ops | Dashboard card | `GET /api/capabilities` (auth) |
| Model tree | Mapping / RDF | Wave C `#model` | SPARQL + model APIs |
| Charts / RCx / FDD | Plotly routes | Wave C ECharts | `/api/analytics/*`, `/api/fdd/*` |
| Schedules | Operations | Wave D `#schedules` | Durable jobs + AFDD status |
| CSV / admin | Mapping, admin | Wave E | Existing import/admin REST |
| Inspect | Trace overlay | Wave E | Historian + analytics |

Guardrails: same-origin `/api` only; CSP without `unsafe-inline` / `unsafe-eval`; no reference Clerk/LAN or BACnet control paths.
