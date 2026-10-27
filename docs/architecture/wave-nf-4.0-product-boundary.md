# Wave-NF 4.0 product boundary

**Status:** Documented 2026-10-19. Soft-OPEN ≠ FQ.  
**Plan:** [`.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md`](../../.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md)  
**Decision:** [ADR-011](adr-011-pluggable-data-provider.md) · [ADR-010](adr-010-timescale-hard-cutover.md) · [OT archive](ARCHIVE_OT_EDGE.md)

No row below is **qualified**. No 4.0 image is claimed **deployed**. A lab smoke or a unit test is not an N12 pilot.

## Product boundary

Normal 4.0 ingest is HTTPS `DataProvider` drivers inside `openfdd-central`, writing normalized samples through the existing Timescale live-historian path. The product UI is `openfdd-web`.

| In the 4.0 product | Role |
| --- | --- |
| `openfdd-central` | Rust JWT REST, provider poller, SQL FDD, Timescale ingest |
| `openfdd-web` | React product UI |
| Timescale (`openfdd-timescale`) | Sole product historian. No Parquet / DataFusion on this path |
| `openfdd-mcp` | Optional. Read-first stdio against central. Not required to ingest |
| Provider worker | Optional future process. Today the poller is a task inside central. Shared leases (N8) are not done, so extra replicas are not a supported 4.0 scale path |

| Not the normal 4.0 ingest path | What remains true |
| --- | --- |
| `openfdd-fieldbus`, `openfdd-mqtt` | Still in this repo. Archived for normal 4.0 ([`ARCHIVE_OT_EDGE.md`](ARCHIVE_OT_EDGE.md)). Not the portal ingest path |
| CSV / package import | Lab and migration path. Not Wave-NF portal ingest |
| Ace IoT | Stub only. Health stays `not_implemented` |
| ACME retrofit | Later (M13). This boundary does not change ACME |
| Building 100 history | Must not be reseeded by this wave |
| Data backups | Not part of 4.0 provider ingest |
| NF `POST /api/v1/point/data` | A write. History reads are `GET /api/v1/point/data` only |

Haystack roles stay. Remote Haystack transport retires with the OT pipelines. Roles on the provider path come from an explicit `provider_point_id` map or a SPARQL binding set. Display names do not invent roles.

## Status labels

| Label | Meaning |
| --- | --- |
| **prototype** | Compiles or connects. Known integrity gaps remain |
| **implemented** | Code or docs land the stated contract |
| **tested** | Gate evidence is recorded for that contract |
| **deployed** | A published sha is pinned on the hub |
| **qualified** | N12 matrix plus a bounded SoftOPEN pilot passed |

## Requirements-to-test matrix

Evidence is what exists in this tree on 2026-10-19. In-progress rows owned by other PRs are **prototype** until those PRs merge and their own evidence is recorded.

| ID | Requirement | Status | Evidence | Still open |
| --- | --- | --- | --- | --- |
| N0 | Write this boundary and the label matrix | implemented | This document | Not a test gate, not deployed, not qualified |
| Shape | central + web + Timescale is the 4.0 product | prototype | ADR-011, ADR-010, `services/central` version 4.0.0 | GHCR publish and hub pin are N13 / M10 |
| MCP | Optional read-first MCP | prototype | Provider health / sites tools | Scoped jobs and receipts (N10) |
| Worker | Optional worker, separate from API replicas | prototype | In-process poller in `providers/poller.rs` | Postgres queue and leases (N8). Do not add replicas yet |
| N1 | OT archive snapshot, prune keep, isolated restore | prototype | `archive/ot-edge/unqualified-cdaa4f15/` plus prune keep for `ot-archive-*`. No `ot-mqtt-fieldbus-last-good-3.6.18` tag | Isolated boot, health, and replay were not run. Not a verified freeze |
| N2 | Tenant filter, fail-closed secrets, no OAuth redirects, byte and time bounds, typed errors | implemented | `providers/http_policy.rs`, `providers/error.rs`, merged Wave-A | DNS-at-connect rebinding pin; hot credential reload. Not a security qualification |
| N3 | Source-neutral committed model and scoped SPARQL plans | prototype | Explicit point map and binding-set merge in `providers/map.rs` | Committed revision model is a separate change |
| N4 | Provider history contract; Ace stays NotImplemented | prototype | NF `fetch_history` is `GET /api/v1/point/data`. Ace health is `NotImplemented` | No single capability registry type beyond the trait plus concrete drivers |
| N5 | Durable per-device hourly jobs, receipts, catch-up | tested | `providers/hourly.rs`, `hourly_exec.rs`, `sql/schema/04_provider_hourly_jobs.sql`. Fixture tests. NF history stays `GET /api/v1/point/data` | Not deployed. Sample upsert and job receipt are separate writes. Full ledger UI is N7 |
| N6 | Per-equipment type, source timestamp / unit / quality, truthful persist counts | implemented | `providers/writer.rs` receipt uses persisted rows | Not an N12 storage qualification |
| N7 | Coverage ledger and bounded reconciliation | prototype | Plan states the NF update-log `403` limit | No coverage ledger. Range reads are not gapless |
| N8 | Shared Postgres queue and leases | prototype | Not in the poller | One central process starts every configured site poller |
| N9 | Open-Meteo read-only weather provider | implemented | `providers/meteo.rs` on the same completed-hour scheduler as NF. Public GET, host allowlist, 48 h window, series cap, timeouts, byte cap, typed errors. `hourly_exec` calls `normalize_mapped`, then `writer::ingest_samples` | Live API is not called from CI. Not deployed |
| N9-fixture | Contractor conformance fixture | tested | Offline fixture `providers/fixtures/open_meteo_hourly.json` and `providers/conformance.rs` (`open_meteo_fixture_passes_contractor_conformance`). No live network | This is a unit gate, not a SoftOPEN pilot |
| N10 | Scoped REST / MCP jobs, receipts, gaps | prototype | Existing read-first tools | OT tool discovery is not fully retired from every recipe |
| N11 | Providers / sites / model / ledger UI | prototype | Ops Providers view exists | Ledger, gap, and source-neutral analytics UI are separate work |
| N12 | Full acceptance matrix and bounded NF pilot | prototype | Not started here | No portal flood. No qualification claim |
| N13 | Phased publish and truthful remaining status | prototype | This matrix | No GHCR publish, no stack re-pin, no PyPI publish from this work |
| Ace | Ace IoT driver | prototype | `providers/ace_stub.rs` returns `NotImplemented` | Driver not started. Conformance test locks the stub |
| M13 | ACME NF retrofit | prototype | Deferred in the plan | Do not retrofit ACME in this change |
| Weather roles | Web OAT series enter Timescale only through an explicit map | implemented | Point map keys are Open-Meteo series ids (`temperature_2m`, …). Roles such as `web-outside-air-temp` are operator config | Display names in a payload must not become roles |

## Open-Meteo contract (N9)

The adapter is a public, read-only `DataProvider`. It does not take OAuth client secrets. Config rejects credential fields. Allowed origins are `https://api.open-meteo.com`, `https://historical-forecast-api.open-meteo.com`, and `https://archive-api.open-meteo.com`.

Each request is one GET. The query carries latitude, longitude, the mapped series ids, and a UTC date span. The span is refused when the window is longer than 48 hours or the site maps more than eight allowlisted series. The HTTP client disables redirects and uses the shared connect, total, and body limits. Failures are `ProviderError` codes (`contract`, `body_too_large`, `deadline_exceeded`, `throttled`, `redirect_rejected`, `transport`, `config_invalid`). Response bodies are not copied into health or error text.

Parsed rows are `RawProviderPoint` values whose `provider_point_id` is the series id. The hourly job calls `normalize_mapped` with the site point map, then `writer::ingest_samples`. That writer is the only Timescale write. The contractor gate uses `map_provider_samples`, which calls the same `normalize_mapped`. Unmapped ids, including any display-name decoy, are dropped. Ace is not on this path.

CI loads `providers/fixtures/open_meteo_hourly.json` from disk. It does not call Open-Meteo.

## What this document does not claim

- Gapless NF history. The lab update log returned 403 on 2026-10-18.
- That the lab plate-sensor `mat` stamp is AHU mixed air.
- A passing full-matrix qualification, a published 4.0 sha, or a hub pin.
- That fieldbus and MQTT are deleted. They are archived for normal 4.0 and still present in the repo.
