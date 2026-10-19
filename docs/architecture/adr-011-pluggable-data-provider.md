# ADR-011: Pluggable DataProvider ingest (Wave-NF / 4.0)

**Status:** Accepted (2026-10-18). Soft-OPEN ≠ FQ.  
**Plan:** [`.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md`](../../.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md)

## Context

The money Soft-OPEN path is **not** BACnet → MQTTS fieldbus Soft-OPEN. Vendor
edges (Normal Framework portal today; Ace IoT later) own device poll. Open-FDD
owns HTTPS drivers → Haystack RDF / roles → Timescale → SQL FDD/analytics.

OT fieldbus/MQTTS stay **in this repo** as an unqualified archive snapshot
(`archive/ot-edge/unqualified-cdaa4f15/`). They are not the 4.0 default stack,
not a Soft-OPEN driver, and not a new GitHub repo. Haystack semantics stay.

## Decision

1. **Pluggable HTTPS drivers** inside `openfdd-central` — authenticate,
   catalog query, and history. NF and Ace are separate drivers. The hourly
   worker calls the NF driver directly.
2. **Normalized samples** → existing Timescale writer (`SampleRow` /
   `TelemetryEnvelope` tags: `building_id`, `equipment_id`, `role`).
3. **NF first robust driver** — OAuth client-credentials +
   `POST /api/v1/point/query` (bosspi checkpoint). Ace IoT ships as a stub.
4. **Role / equipment identity via SPARQL + semantic_meta only** — inventory-
   approved roles from Haystack RDF templates, or explicit `provider_point_id` →
   `{equipment_id, role}` maps. **Forbidden on the product path:** substring,
   prefix, `contains`, `LIKE`, or display-name grepping of NF point names to
   invent roles.
5. **Slimmer Soft-OPEN stack** — `portal` recipe: central + web + Timescale.
   fieldbus/mqtt are the explicit archive lane
   (see [`ARCHIVE_OT_EDGE.md`](ARCHIVE_OT_EDGE.md)). There is no verified
   `3.6.18` OT freeze tag.
6. **MCP** — read-first provider health / sites tools; writes stay gated.
7. **Hourly history jobs** — each modeled device is due for the last completed
   hour. The job copies every source sample in the hour. NF history is
   `GET /api/v1/point/data` only (`POST` on that path writes). Checkpoints,
   receipts, and catch-up live in Postgres. The NF update log returned HTTP 403
   on the lab key, so health states a bounded reconcile sweep and does not claim
   gapless replication.
8. **Provider registry** — each driver advertises explicit capabilities
   (`authenticate`, `latest`, `fetch_history`, `bounded_windows`, `update_log`).
   `latest` does not imply history. NF `fetch_history` is GET inside
   `MAX_HISTORY_WINDOW`. Ace advertises every capability as `NotImplemented`.
9. **Coverage ledger** — health separates transport probe, requested-window
   completeness, durable commit, source freshness, late reconciliation, and
   unrecoverable retention expiry. The ledger is derived from hourly jobs,
   receipts, checkpoints, and gaps. One latest sample cannot advance it.

## Consequences

- Railway Soft-OPEN hub can poll NF portals over HTTPS without MQTT/fieldbus.
- ACME live NF retrofit waits until bosspi Soft-OPEN is stable (marinate) and
  Grok deploy tools are rewritten for the slimmer stack.
- Soft-OPEN 3620 ART sweep remains deferred tip-bug backlog.

## Links

- Checkpoint smoke: `scripts/nf/read_sensors.py`
- OT snapshot: `archive/ot-edge/unqualified-cdaa4f15/` · `ARCHIVE_OT_EDGE.md`
- Prior: [ADR-010](adr-010-timescale-hard-cutover.md)
