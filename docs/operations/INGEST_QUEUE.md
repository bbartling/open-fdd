# Ingest queue (Wave-NF N8 / N10)

Shared work list for portal history reads. Kubernetes is not required.
Host vertical sizing and a manually chosen replica count are not an autoscaler.

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

The scheduler enqueues at most `OPENFDD_INGEST_CATCHUP_HOURS` (default 6, max 48) exact UTC hours per mapped device. That is a bound, not the N5 checkpoint walk. Duplicate keys insert nothing. Portal caps (`OPENFDD_INGEST_PORTAL_MAX_IN_FLIGHT`, `OPENFDD_INGEST_PORTAL_MAX_PER_MINUTE`) are shared by every worker. A 429 pause on one portal does not free another portal's cap. Claim size is at most 32 jobs. The queue pool is at most 8 connections (`OPENFDD_INGEST_QUEUE_MAX_CONNECTIONS`, default 4).

Windows are half-open UTC intervals `[start, end)`. The end instant is excluded. A job accepts a length of 60 to 3600 seconds when `start` is aligned to that length. A 3600-second window is still one exact UTC hour, including the civil hours that spring forward or fall back.

Each job is owned by one row. The unique key is the identity above. A claim commits before any portal read. Finish requires the current owner, fencing token, and an unexpired lease. An expired lease can be claimed by another worker; the previous token cannot finish. A provider HTTP success, a row count, or a checkpoint does not commit the job.

Coverage is assessed per expected point. Dispositions are `present`, `no_sample_expected`, `no_sample_received`, `late_arrival`, `source_unavailable`, `genuine_gap`, and `expectation_unspecified`. `no_sample_expected` is a cadence or COV rule that asked for nothing in the window. `no_sample_received` is an expected slot or heartbeat that the completed page did not contain. An omitted series is `source_unavailable` and stays retryable. A finished page that is missing interval slots is `genuine_gap` and stays `partial`. A truncated page is not treated as a genuine gap. Commit is allowed only when every expected point is `present`, `no_sample_expected`, or `late_arrival`. Rows that have not been reconciled stay `not_assessed`. A point whose binding states no expectation is `not_assessed`: its samples are written, but the window summary is `not_assessed`, not `complete`. A window where every point expected zero slots and returned none is also `not_assessed`. Zero expected slots is never a complete window. The verified cursor only advances over committed windows whose summary is `complete`; a committed `not_assessed` window is a cursor hole with code `not_assessed`. The jobs list rolls those summaries up; an empty gap list stays `not_assessed` and does not claim the window was complete.

Binding expectations come from the committed model. A SPARQL binding set may add `ing:quantity`, `ing:historyMode` (`interval` or `cov`), `ing:cadenceSecs` (interval, 1-86400), and `ing:heartbeatSecs` (COV, 1-604800). A non-integer, zero, out-of-range, mode-less, or mismatched value rejects the binding set; it is not dropped. These fields, the units, and the approval state are part of the model revision hash, so a cadence, heartbeat, unit, quantity, or approval change starts a new revision. Point-map bootstraps carry no expectation and stay `not_assessed`.

The gap API says `guarantee: bounded_windows_only` and `update_log: not_claimed`.

Writes of the same point and timestamp are idempotent. The first value is kept. A different value is a conflict and does not rewrite the stored bits. That ledger is queue state (`ingest_applied_sample`). It does not replace or rewrite historian samples. A receipt is written in the same transaction as a committed or partial finish. Retry, throttle, timeout, and a model change do not write a receipt and do not advance the job to `committed`. A model or point-set change observed at finish becomes `permanent_failure` / `model_revision_changed`.

## Daily catch-up and the verified cursor

A site can opt into a daily schedule with `schedule_mode = "daily"` and an IANA `schedule_timezone` (for example `America/Chicago`). The default is `periodic`, which keeps the hourly planner. A timezone without daily mode, daily mode without a timezone, or an unknown zone is rejected when the site config loads.

In daily mode the planner enqueues the previous local day once local midnight plus the publication delay (`OPENFDD_INGEST_PUBLICATION_DELAY_SECS`, default 300) has passed. A day is 23, 24, or 25 hours across DST changes. Windows are cut at the largest of 1 h, 30 min, 15 min, 5 min, or 1 min that fits both day boundaries, so half-hour zones use 30-minute windows. `OPENFDD_INGEST_DAILY_CATCHUP_DAYS` (default 2, range 1-7) sets how many past days are re-planned. Existing windows are not duplicated.

A daily window with a recoverable gap or a retryable error waits for the next daily run instead of retrying within the hour. When the next run would fall outside the source retention, the window becomes `permanent_failure` / `retention_exceeded`, it is listed as a gap, and operator retry is refused.

`ingest_coverage_cursor` stores, per tenant, site, provider, device, and model revision, the instant through which every overlapping job is committed. It only moves forward. The first instant that is not verified is stored as a hole with the blocking job state and code, or `not_scheduled` when no job covers it.

## Coverage status

`GET /api/ingest/coverage-status?site_id=` reports, per configured provider, the schedule mode and timezone, the planned end (`planned_through`), the next run, the approved, withheld, and discovered point counts from the committed plan, and each device's verified cursor. It reads only stored rows: the active plan, `ingest_coverage_cursor`, and the gap list. It does not run a fetch.

A device is `verified` only when its cursor reaches `planned_through`. Otherwise its hole decides: no hole, `not_scheduled`, `queued`, or `leased` is `behind`; a committed window with code `not_assessed` is `not_assessed`; any other hole (partial, retry wait, permanent failure, committed but incomplete) is `gap`. A device with no cursor is `not_assessed`, and a provider with no committed plan is `not_configured`. The provider and site take the worst device state. The oldest gap is the first gap row for the active revision within the first 200 rows; `gap_scan_truncated` is set when none matched. The Operations page shows this as **Schedule and coverage** under the selected site.

## HTTP and MCP

JWT scoped like other tenant routes. Empty membership returns no rows. Operators (`confirm` on MCP, plus `OPENFDD_MCP_ALLOW_WRITES=1`) may retry or backfill with an idempotency key. Backfill accepts 1–48 exact UTC hours.

| Method | Path |
| --- | --- |
| GET | `/api/ingest/jobs` |
| GET | `/api/ingest/receipts` |
| GET | `/api/ingest/gaps` |
| GET | `/api/ingest/coverage-status` |
| GET | `/api/ingest/queue` |
| GET | `/api/ingest/queue/scale-preview` |
| POST | `/api/ingest/jobs/{job_id}/retry` |
| POST | `/api/ingest/backfill` |

Normal 4.0 MCP `tools/list` includes `openfdd_ingest_jobs`, `openfdd_ingest_receipts`, `openfdd_ingest_gaps`, and `openfdd_ingest_queue`. BACnet, remote Haystack wire, and fieldbus driver tools are omitted and return `ot_transport_retired`. Semantic SPARQL stays. `OPENFDD_OT_TOOLS=1` is the archive lane only.

History reads stay GET. This queue does not POST `/api/v1/point/data`.
