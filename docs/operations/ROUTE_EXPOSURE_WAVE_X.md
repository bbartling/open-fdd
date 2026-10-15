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
| GET | `/api/fdd/plots-by-rule` | Allow scoped | JWT | Soft-OPEN R4 lean role catalog + lean_budget (Timescale); Soft-OPEN ≠ FQ |
| GET | `/api/csv/import/package/mapping/semantic-meta` | Allow scoped | JWT + building | Soft-OPEN R5 `present` flag + `soft_open_neq_fq`; Soft-OPEN ≠ FQ |
| GET | `/api/model/point-resolve` | Allow scoped | JWT + building | Soft-OPEN R5 opaque IRI → `openfdd_key` (+ optional Timescale history); Soft-OPEN ≠ FQ |
| GET | `/api/admin/schema-contract` | Hub admin | Hub admin JWT | Soft-OPEN R8a tip-safe read-only seed_meta + pinned contract; Soft-OPEN ≠ FQ |
| POST | `/api/model/sparql` | Allow scoped | JWT + building | C13 free-form SELECT/ASK **or** `query_id` |
| POST | `/api/model/sparql/query` | Allow scoped | JWT + building | Alias of free-form |
| POST | `/api/model/sparql/upload` | Allow scoped | JWT + building | JSON `{query,building_id}` ≤200KiB |
| POST | `/api/ingest/local` | **Deny** at web edge | Deployment token | Field/OT only |

Soft-OPEN R7 profile ART (≠ FQ): [SOFTOPEN_EXPOSURE_R7.md](../softopen/SOFTOPEN_EXPOSURE_R7.md).

Anonymous SPARQL and unscoped SQL are denied. Mutations/SERVICE/FROM rejected by `ensure_readonly_query`.
