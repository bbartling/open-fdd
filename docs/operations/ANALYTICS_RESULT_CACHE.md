# Analytics / RCx / fault result cache

Parquet result tables for `/api/analytics/*` (including RCx presets and sensor-fault analytics). This is the same Arrow/Parquet family as the historian. It is not the AFDD `{rule_id}.json` blob under rule results. Historian parts are not rewritten when a result file is stored.

## Layout

```text
{storage}/analytics_results/building_id={id}/query_id={query}/query_version={ver}/window={start}__{end}/config={hash16}/results.parquet
```

`{storage}` is `OPENFDD_ANALYTICS_CACHE_ROOT`, otherwise the local file root (`OPENFDD_STORAGE_URL` / `OPENFDD_PARQUET_ROOT`), otherwise the hub parquet root.

Schema name: `analytics-result-parquet-v1`.

| Column | Type | Meaning |
| --- | --- | --- |
| `section` | utf8 | `rows`, `equipment`, `points`, `skipped`, `warning`, or `coverage` |
| `row_index` | uint32 | order inside that section |
| one column per scalar field | float64, bool, or utf8 | typed cell |

Nested objects and arrays are utf8 JSON cells. Provenance is Parquet key/value metadata (`openfdd.*`): full config hash, watermark order, query version, window. The path hash is the first 16 hex chars. A different query version or config hash is a different partition (cache miss).

`building_id` is a request parameter. Empty or unsafe ids (`/`, `\`, `..`, NUL) skip the cache and compute uncached. Request `equipment_ids` are sorted into the config hash. They are not a path segment and they are not a `LIKE` / prefix / contains filter. This cache does not infer `equipType`. The watermark matches hive segments `building_id=` and `building=` only. `equipment_id=` text does not select a building, and a longer id is not a prefix match.

## Freshness

The watermark is the newest historian part order key for that building (`part-YYYYMMDDTHHMMSSZ`, else `year=`/`month=` → first of that month, else mtime). Analytics result files are not part of the watermark.

| Condition | Behavior |
| --- | --- |
| No file, or version/config partition differs | Miss. Compute, write parquet, `cache.hit=false`. |
| Historian order ≤ cached order | Hit. Do not recompute. |
| Historian order > cached order | `stale: true` on the JSON body and `cache.stale`. Default serves the last rows. |
| `refresh: true` on the request | Always recompute. |
| `OPENFDD_ANALYTICS_CACHE_ON_STALE=recompute` | Watermark advance recomputes instead of serving stale. |

Stale is a structured flag. It is not copied into envelope `warnings`, so Overview does not grow a cache caption.

Routine opens omit `refresh` and use the cache. Explicit operator actions send `refresh: true`: Overview **Update analytics** / **Force refresh analytics** (including the health, weather, and SQL-anomaly sections whose token advanced), a rules-updated refetch of those sections, and **Refresh RCx preset**. Opening a building or an RCx preset does not.

`elapsed_ms` on `cache` is the server time for that read or recompute (hit vs miss).

Fuel bill math (`/api/analytics/fuel`) is not this cache. The global faults summary is not stored under a building id. Sensor-fault analytics (`sensor-faults-v1`) is the fault result table.

## Building RAM

CSV / package buildings are guests.

- First analytics query opens an interactive lease (default **2** concurrent, clamp 1–8, `OPENFDD_MAX_BUILDING_SESSIONS`).
- The historian working set is marked loaded only for the compute job. `finish_job` clears it when the result parquet is written (or the job returns). The lease stays until leave or idle so the active building remains the warm slot without holding Arrow tables.
- Idle default **60s**, clamp 30–120 (`OPENFDD_BUILDING_SESSION_IDLE_SECS`). A timer in central evicts idle CSV leases.
- A third CSV guest evicts the oldest idle CSV lease. If every interactive slot is inside a running job, the API returns **429**.
- `POST /api/sessions/building/leave` with `{ "building_id" }` drops that lease. The SPA calls it when `?site=` changes.
- `GET /api/sessions/buildings` (hub admin) lists `interactive_slots`, `historian_resident`, and `ram_resident`.

`ram_resident` / `historian_resident` are the RSS check. After unload they must not still name the CSV building. The lease list can still name it until leave or idle.

Live MQTTS does not load the full historian. Ingest records a capped row buffer (`OPENFDD_MQTT_INGEST_BUFFER_ROWS`, default 256, max 4096) and at most `OPENFDD_MAX_MQTT_BUILDING_BUFFERS` buildings (default 32). MQTT sessions are not idle-evicted.

Listing datasets (`note_catalog_list`) does not open a session. A hub with hundreds of packages must not keep hundreds of Arrow tables resident. Overview paint prefers the cached parquet partition.

## Acceptance

- On-disk layout and schema above.
- `cache_hit_does_not_recompute_and_records_elapsed` shows a second call does not recompute and records `elapsed_ms`.
- `watermark_advance_is_stale_until_refresh` serves stale rows until `refresh: true`.
- Session tests in `fdd_store` cover idle eviction, capacity, MQTT buffer, and `finish_job` clearing `historian_resident`.
- `watermark_ignores_equipment_id_text_and_id_prefixes` rejects `equipment_id=` text and a longer `building_id` prefix.

## Compliance (Soft-OPEN, not FQ)

| Rule | This change |
| --- | --- |
| No `equipment_id` substring filters | Hive keys are exact: path segment `building_id={caller}` or `building={caller}`, or directory key `building` after one `=`. `equipment_id` text is never searched with `contains`, `starts_with`, or `LIKE`. Request `equipment_ids` are a config-hash input only. |
| No building hardcodes; `building_id` is always a parameter | Product cache, session, ingest buffer, and retention take the caller id. Missing id skips the cache. No default site. Tests use `site-a`. |
| No MQTT CELL/DELTA | Ingest records a row-count buffer under the envelope site id. No new topic mode. |
| Building-agnostic session, cache, and retention | Same limits and layout for every building. `OPENFDD_TEST_DEPLOY` is an env flag, not a site-name branch. |
| No VERSION bump / not FQ | Workspace `VERSION` is unchanged. Edge disk proof is still open. |
