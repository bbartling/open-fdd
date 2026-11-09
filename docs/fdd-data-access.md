---
title: FDD data access
nav_order: 5
---

# Where FDD results live and how API users get them

Open-FDD results are **ordinary NF points**. The `fdd` hook writes them through NF's own point API, so NF stores
them and serves them like any other point: `point/query` for the current state, `point/data` for history. No
Open-FDD service, database or export job is needed to read them. (Everything below was checked in
`nf-app/hooks/fdd.js`, `history.js`, `lib/timescale.js` and `analytics.js`.)

## What is written

Per (site, equip, rule), the hook writes records to the `automation` layer and the `model` layer (uuid derived from
the equip's NF uuid plus the rule id, so it is stable across renames), then one batched `AddData` per chunk
(`POST /api/v1/points/data`).

| Point | Markers | Value | Attributes worth reading |
|---|---|---|---|
| Result point | `point,his,fault,fdd` (rules with a fault output) or `point,his,metric,fdd` | one sample per run: `fault_pct` in `%` (else `fault_hours` in `h`); metric rules: their first output | `fddStatus` (`ok`, `fault`, `not-assessed`, `stale`), `fddReason`, `fddCoverageHours`, `fddLastRun`, `fddWindowHours`, `ruleRef`, `equipRef`, `siteRef`, `equipUuid`, `fddOccSource` |
| Fault timeline point (5.0.3, 68 of 77 rules) | `point,his,fault_timeline` (no `fdd`, no `fault`) | one sample per assessed history timestamp: `1` confirmed fault, `0` ok; **no sample** = not assessed (never written as 0) | `ruleRef`, `equipRef`, `siteRef`, `equipUuid`, `fddKind=fault-timeline`, `fddTimelineOf` (uuid of the result point), `fddTimelineThrough` (newest sample written) |

Not assessed is never healthy: a result with no coverage gets `fddStatus: not-assessed` and no numeric value; a
result that could not be refreshed gets `fddStatus: stale` and keeps its old samples.

The timeline is append-only and grid-aligned to the rule pack's 5-minute grid.

## Checking that results are fresh

A result is only trustworthy if it is recent. From 5.0.5 a run that refreshed nothing fails instead of reporting success, and
`nf_app_sync.py doctor` has an **fdd freshness** check (FAIL when computed points are older than 2x the fdd schedule while raw
history is fresh). Stale results say why in `fddReason`: `required roles missing`, `unit unusable (role ...)` or
`no input data in window (newest sample at <ISO>)`. The `history` hook answers an empty range with `ok: true`, `reason`
and `newest_source_ts`, and a database failure with `ok: false` and the error.

## Optional: Timescale `openfdd.fdd_results`

Only on the **full edition with the TimescaleDB engine**: the `fdd` hook also writes one row per (run, equip, rule)
(`fault_pct`, `fault_hours`, `covered_hours`, `metric`, `engine`, window) into the hypertable `openfdd.fdd_results`
(`nf-app/timescale/install.sql`). It is a convenience copy for SQL users, not the source of truth; the NF points
above exist either way. It has no per-timestamp timeline (that lives in the NF timeline points). The `history` hook
reads NF's own sample table (long-range min/avg/max per bucket) and needs Timescale too; without it the hook fails with
`config.timescale is not set`.

## Recipes for an API client

All reads work with a read-only NF API key (LAN, or through the Normal Online portal with a bearer token). Base
paths are the same on both.

### 1. Current status of every fault, in one query

```
POST /api/v1/point/query
{ "layer": "default", "pageSize": 500,
  "structuredQuery": { "and": [ { "field": { "property": "markers", "text": "fdd" } },
                                { "field": { "property": "markers", "text": "fault" } } ] } }
```

(One marker per clause.) The `default` layer merges every layer, so each record carries the attributes above plus
`latestValue`. Follow `nextPageToken` until empty. A fault is `attrs.fddStatus == "fault"`; `latestValue` is the
percentage of covered time in the trailing window (default 24 h). Group by `siteRef` / `equipUuid` and `ruleRef`.
Treat `not-assessed` and `stale` as **unknown**, not healthy.

### 2. A daily bulk download of when faults happened

1. Query the timeline points once: same body with `"text": "fault_timeline"`. Cache the uuid list; it only changes
   when equipment or rules change.
2. `GET /api/v1/point/data?uuids=<u1>&uuids=<u2>&from=<ISO>&to=<ISO>&window=300s&method=MAX`. `MAX` over the 5-minute
   grid keeps a confirmed `1` visible; `FIRST`, `LAST`, `AVERAGE`, `MIN`, `SUM`, `COUNT` also exist. Practical limits
   (the shipped client uses them): batches of about 40 uuids per request, time pieces of at most 7 days, and NF caps a
   series at about 10 000 samples per request (a day at 5 minutes is 288 per point, so a 24 h pull is far under it).
3. Missing timestamps in the answer are **not assessed**; do not fill them with 0.

The `open-fdd-nf` CLI and `open_fdd.nf.client.NFClient.query_all` / `point_data` do the paging and batching
([Python tools](python-tools.html)).

### 3. The analytics hook

`POST /api/v1/apps/open-fdd/hooks/analytics` with `{"args": {"tool": "get_fdd_fault_timeline", "equip": "...", "rule": "...", "days": 1}}`,
then read the answer from `GET /api/v1/apps/open-fdd/hooks/analytics/runs?include_results=true`, or run
`open-fdd-nf analyze fault-timeline ...`. It also offers weekly runtime, mechanical cooling hours, economizer
residuals and role binding, each keyed by `equipUuid`. It is read-only and the answer is capped at about 200 KB
(`truncated: true` when cut). Starting a hook is a POST that a read-only key may be refused (use the console login), so for an
unattended integrator prefer recipes 1 and 2.

### 4. Live

`GET /api/v1/point/updates/data?uuids=...&wait=true` pushes new samples (chunked). Useful for a dashboard, not for
a once-a-day pull.

## Recommended pattern for an integrator that pulls once a day

1. Once (and weekly): `point/query` for `fdd` + `fault` points and for `fault_timeline` points; store
   `uuid`, `siteRef`, `equipUuid`, `equipRef`, `ruleRef`, `unit`.
2. Daily, after the hourly hook has run: `point/query` again for status (recipe 1, one paged call).
3. Daily: `point/data` for the timeline uuids with `from` = your last watermark, `to` = now, `window=300s`,
   `method=MAX`, batched as above. Use `fddTimelineThrough` on each timeline point to know how far NF has written
   before you advance your own watermark; re-pulling an overlap is harmless.
4. Keep "no sample" as unknown.
5. Use a read-only API key; the hook-start routes are not needed.

## Gaps and recommendations (written down, not implemented)

- **No single "all faults, with timeline, as one file" endpoint.** The client has to do the two-step query plus
  batched `point/data`. Recommendation: an on-request `export` hook (or an `open-fdd-nf` command) that returns
  status plus timeline for a date range as CSV/JSON, paged, with the equip and site names already joined.
- **The analytics hook cannot be used with a read-only key and caps at about 200 KB**, so it is not a bulk channel.
- **No change feed for results.** A client must poll and track its own watermark (`fddTimelineThrough` helps).
  Recommendation: also expose a `fddRunSeq` or a last-run summary point so a client can tell "a new run finished".
- **9 of 77 rules have no timeline** (ratio, count and window-statistic rules): only their per-run result sample
  exists. A client wanting daily history for those uses the result point's samples (`point/data`, one per run).
- **Retention is NF's.** How long result and timeline samples stay depends on NF's history retention for the
  point's layer; we did not find an Open-FDD setting for it. Pull daily and keep your own copy if you need more.
- **Fault state in the Timescale table is run-level only** (see above); do not treat it as the timeline.
