---
title: API reference
nav_order: 11
---

# NF API reference

Open-FDD uses the Normal Framework API. Results are ordinary NF points. This page describes generic read routes and
the Open-FDD result shape; use the NF documentation for routes not listed here.

Set the base URL and credentials in your local environment. Do not place credentials in a URL or commit them:

```bash
export NF_BASE_URL=<reachable-console-base-url>
export NF_USER=<read-only-user>
export NF_PASSWORD=<secret>
```

Use Basic auth for a local console, or the bearer token issued by the Normal Online portal. Portal API keys are
read-only. Hook invocation and app deployment may require console authentication. Always use TLS for remote access.

## Point metadata

### POST /api/v1/point/query

Query point metadata and current values. A query body selects a layer and uses structured query clauses:

```json
{
  "layer": "default",
  "pageSize": 500,
  "structuredQuery": {
    "and": [
      {"field": {"property": "markers", "text": "point"}},
      {"field": {"property": "markers", "text": "example-role"}}
    ]
  }
}
```

One marker is used per clause. Use the model layer for site, equipment, and device records; default combines layers
and exposes current values. The supported pager uses `pageOffset` with `totalCount`; it does not use a
`nextPageToken`. Open-FDD reads every page and rejects repeated records.

### GET /api/v1/equipment/classes

Returns the NF class vocabulary. The result can be paged; query parameters accepted by the installed NF version are
authoritative. Open-FDD uses classes and Haystack markers to bind points to named roles. See [Modeling](modeling.html).

## Point history

### GET /api/v1/point/data

Read resampled point history. Common query fields include repeated `uuids`, `from`, `to`, `window`, and
`method`. The response contains timestamps and values keyed by point id. Supported aggregation methods depend on
NF; Open-FDD uses averages for signals and maxima for fault timelines.

Use bounded requests: batch point ids and split long ranges into time chunks. The app limits request URL size and
pages range reads where supported. A missing timestamp means no sample; it is not a zero. The NF API and the
[Python client](python-tools.html) provide the response envelopes for your NF release.

## Open-FDD result points

The hourly Full FDD hook writes one equipment summary per rule and, for sensor sweeps, one row per assessed sensor.
Result points use fault or metric markers and carry attributes such as:

| Attribute | Meaning |
|---|---|
| `ruleRef`, `equipRef`, `siteRef` | Rule and modeled equipment/site ids |
| `fddStatus` | `fault`, `ok`, `not-assessed`, or `stale` |
| `fddReason` | Why a result is unknown or stale, when applicable |
| `fddCoverageHours` | Assessed time in the current window |
| `sensorRef`, `roleRef` | Sensor UUID and role on a per-sensor result |
| `fddSensorFaultHours` | Per-sensor hours included on the equipment summary |

No coverage is not healthy: status is not-assessed and there is no numeric fault value. Stale means the current run
could not refresh the point; it does not erase earlier history.

### Query current fault status

Use point/query with clauses for the fault result markers. Read `attrs.fddStatus`, `attrs.ruleRef`,
`attrs.siteRef`, and `attrs.equipRef`. Treat `not-assessed` and `stale` as unknown, not healthy. The numeric
latest value is expressed in the point's declared unit; fault percentage uses the 0–100 scale.

### Read fault timelines

Timeline points use the fault_timeline marker. Read them with point/query, then call point/data in bounded chunks.
The series records 1 when a fault is confirmed and 0 when assessed healthy. A missing timestamp is unknown. Use
`fddTimelineThrough` as a watermark when advancing a client-side cursor.

## Hook routes

NF exposes app hooks under `/api/v1/apps/{app-id}/hooks/{hook-name}`. POST to a hook route to start a run; read
results from its `/runs?include_results=true` route. The browser/app uses the scheduled Full hooks for FDD and
weather; the SPARQL hook is on request. A successful HTTP response means NF accepted the run; inspect run status and
results before treating it as complete.

## Timescale copy

Full installations using Timescale may also store a run-level copy in `openfdd.fdd_results`. It is optional and
not the source of truth. NF result points and their histories remain the normal API surface. See the
[Timescale setup guide](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale).
