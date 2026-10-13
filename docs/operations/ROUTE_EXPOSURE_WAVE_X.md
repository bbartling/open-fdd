# Wave-X route exposure manifest (X2b / C3)

Soft-OPEN ≠ FQ. Source policy: `.cursor/agents/deployment_route_exposure_wave_x_20261013.md`.

## Profiles

| Profile | Public entry | Private | OT |
| --- | --- | --- | --- |
| Railway/cloud | HTTPS web → nginx → central | Timescale + mqtt | Fieldbus on-prem → MQTTS only |
| Full OT LAN | Caddy HTTPS → web → central | Timescale + drivers | Local SQL ingest; optional MQTTS |
| Field-only | No public API | Collector + spool | OT LAN; outbound MQTTS |

## Product routes added this train

| Method | Path | Cloud | Auth | Notes |
| --- | --- | --- | --- | --- |
| GET | `/api/fdd/plot` | Allow scoped | JWT + building | C12 lean Plotly; max_points≤5000 |
| POST | `/api/model/sparql` | Allow scoped | JWT + building | C13 free-form SELECT/ASK **or** `query_id` |
| POST | `/api/model/sparql/query` | Allow scoped | JWT + building | Alias of free-form |
| POST | `/api/model/sparql/upload` | Allow scoped | JWT + building | JSON `{query,building_id}` ≤200KiB |
| POST | `/api/ingest/local` | **Deny** at web edge | Deployment token | Field/OT only |

Anonymous SPARQL and unscoped SQL are denied. Mutations/SERVICE/FROM rejected by `ensure_readonly_query`.
