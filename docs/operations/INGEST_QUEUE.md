# Ingest queue (Wave-NF N8 / N10)

Shared work list for portal history reads. Kubernetes is not required.
Railway vertical sizing and a manually chosen replica count are not an autoscaler.

## Stages

| Stage | What landed | What it is not |
| --- | --- | --- |
| 1 | Durable jobs, one scheduler lease, one bounded worker | A measured capacity claim |
| 2 | Several workers claim with `SKIP LOCKED`, fencing tokens, and per-portal budgets | Permission to run a poller in every API replica |
| 3 | Dry-run `GET /api/ingest/queue/scale-preview` | **SoftOPEN defer —** live replica changes. The preview sets `live_control: false` and does not call a platform API |

## Who runs what

| `OPENFDD_PROCESS_ROLE` | Scheduler / worker | HTTP |
| --- | --- | --- |
| `api` | Never. `OPENFDD_PROVIDER_POLL=1` is ignored | Yes |
| `worker` | Yes, through the shared queue | Optional |
| `combined` (default) | Yes, through the shared queue | Yes |

Replicas coordinate only when `OPENFDD_DATABASE_URL` is set. The worker applies `sql/schema/04_ingest_queue.sql` on connect. Without that URL the worker stays idle unless `OPENFDD_INGEST_QUEUE=memory` is set for a single process. Memory mode is not replica-safe.

`OPENFDD_PROVIDER_POLL_MODE=legacy` plus `OPENFDD_ALLOW_UNSAFE_POLLER=1` restores independent site loops. That path is not safe with more than one process. API role still refuses it.

## Job identity

Wave-B hourly records use the same unique key:

```text
tenant + canonical_site + provider_instance + device
+ model_revision + logical_window_start + logical_window_end + shard
```

States: `queued`, `leased`, `retry_wait`, `committed`, `partial`, `permanent_failure`, `cancelled`.

A finish must present the current owner, fencing token, and an unexpired lease. An old worker cannot commit after the lease moves. Claims commit the database transaction before any portal read.

The scheduler enqueues at most `OPENFDD_INGEST_CATCHUP_HOURS` (default 6, max 48) exact UTC hours per mapped device. That is a bound, not the N5 checkpoint walk. Duplicate keys insert nothing. Portal caps (`OPENFDD_INGEST_PORTAL_MAX_IN_FLIGHT`, `OPENFDD_INGEST_PORTAL_MAX_PER_MINUTE`) are shared by every worker. A 429 pause on one portal does not free another portal's cap.

Coverage on these rows is `not_assessed`. The gap API says `guarantee: bounded_windows_only` and `update_log: not_claimed`. A full coverage ledger stays with N7.

## HTTP and MCP

JWT scoped like other tenant routes. Empty membership returns no rows. Operators (`confirm` on MCP, plus `OPENFDD_MCP_ALLOW_WRITES=1`) may retry or backfill with an idempotency key. Backfill accepts 1–48 exact UTC hours.

| Method | Path |
| --- | --- |
| GET | `/api/ingest/jobs` |
| GET | `/api/ingest/receipts` |
| GET | `/api/ingest/gaps` |
| GET | `/api/ingest/queue` |
| GET | `/api/ingest/queue/scale-preview` |
| POST | `/api/ingest/jobs/{job_id}/retry` |
| POST | `/api/ingest/backfill` |

Normal 4.0 MCP `tools/list` includes `openfdd_ingest_jobs`, `openfdd_ingest_receipts`, `openfdd_ingest_gaps`, and `openfdd_ingest_queue`. BACnet, remote Haystack wire, and fieldbus driver tools are omitted and return `ot_transport_retired`. Semantic SPARQL stays. `OPENFDD_OT_TOOLS=1` is the archive lane only.

History reads stay GET. This queue does not POST `/api/v1/point/data`.
