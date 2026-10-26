# Analytics / RCx / fault result cache

> **Status: known gap, not permitted.** Storage mandate: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([`openfdd_agent_spec/DATA_CONTRACT.md` § Storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)). Derived FDD / analytics results persist in PostgreSQL or bounded memory. Parquet, Arrow, Arrow IPC, Feather and DataFusion are prohibited in product storage, caching, execution and dependencies.
>
> The Parquet cache described below is what current code in `crates/fdd_store` (`analytics_cache.rs`) and `services/central/src/analytics/result_cache.rs` still does. It is being removed in Wave P2. This page records that behavior so operators and agents can recognize it; it does not permit it. Do not extend the Parquet layout, add columns, add a new schema version, or point new features at it. The freshness contract (cache key, watermark, `stale`, `refresh`) and the building-RAM rules carry over to the PostgreSQL result store.

Current (known-gap) behavior: Parquet result tables for `/api/analytics/*` (including RCx presets and sensor-fault analytics). It is not the AFDD `{rule_id}.json` blob under rule results. Historian rows are not rewritten when a result file is stored. The older statement that this is "the same Arrow/Parquet family as the historian" is historical, superseded by the Timescale-only mandate: the historian is Timescale.

## Layout

```text
{storage}/analytics_results/building_id={id}/query_id={query}/query_version={ver}/window={start}__{end}/config={hash16}/results.parquet
```

`{storage}` is `OPENFDD_ANALYTICS_CACHE_ROOT`, otherwise the local file root (`OPENFDD_STORAGE_URL` / `OPENFDD_PARQUET_ROOT`), otherwise the hub parquet root.

Schema name: `analytics-result-parquet-v2`. Explicit JSON nulls stay on the section that set them (`openfdd.section_keys`), so an unknown health flag still returns `{flag}_fault_h: null`. `analytics-result-parquet-v1` files are cache misses.

| Column | Type | Meaning |
| --- | --- | --- |
| `section` | utf8 | `rows`, `equipment`, `points`, `skipped`, `warning`, or `coverage` |
| `row_index` | uint32 | order inside that section |
| one column per scalar field | float64, bool, or utf8 | typed cell |

Nested objects and arrays are utf8 JSON cells. Provenance is Parquet key/value metadata (`openfdd.*`): full config hash, watermark order, query version, window. The path hash is the first 16 hex chars. A different query version or config hash is a different partition (cache miss).

`building_id` is a request parameter. Empty or unsafe ids (`/`, `\`, `..`, NUL) skip the cache and compute uncached. Request `equipment_ids` are sorted into the config hash. They are not a path segment and they are not a `LIKE` / prefix / contains filter. This cache does not infer `equipType`. The watermark matches hive segments `building_id=` and `building=` only. `equipment_id=` text does not select a building, and a longer id is not a prefix match.

## Freshness

The cache key includes the result contract (`analytics-result-contract-v2`), the analytics SQL pack content hash plus the FDD pack fingerprint, and the site model revision (equipment stamps, role map, and point map). Storage layout stays `analytics-result-parquet-v2`. That schema name is not the result contract.

When Timescale is the historian, freshness uses the scoped sample watermark and coverage for the request window: sample count, valued count, distinct series, min and max timestamps, and the value sum. Named equipment is an exact key-token match. A longer id is not a prefix match. Weather-stamped equipment stays in that scope. Parquet part order is not the Timescale watermark. `Ok(0)` from a Parquet scan means no parts were found. A failed or unreadable watermark read is `watermark_status: unavailable` and is never a fresh hit (`stale: true` when a prior envelope is served).

| Condition | Behavior |
| --- | --- |
| No file, or version/config/contract/pack/model partition differs | Miss. Compute, write parquet, `cache.hit=false`. |
| Persisted envelope has no contract, pack, model, or known watermark | Incompatible. Recompute. Do not serve it as fresh. |
| Same identity and the same known watermark and coverage | Hit. Do not recompute. |
| Same identity, known watermark or coverage moved | `stale: true` on the JSON body and `cache.stale`. Default serves the last rows. |
| Watermark or model read failed | Not a hit. Default serves the last compatible rows with `stale: true` and `watermark_status: unavailable`. |
| `refresh: true` on the request | Always recompute. A failed watermark read still reports `stale: true`. |
| `OPENFDD_ANALYTICS_CACHE_ON_STALE=recompute` | Watermark advance recomputes instead of serving stale. |

Derived cache repair removes `analytics_results/building_id={id}` and `analytics_result` rows for that building. It does not delete historian samples or labeled `fdd_run` / rule-result files.

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

**Historical, superseded by the Timescale-only mandate:** live MQTTS ingest once recorded a capped row buffer (`OPENFDD_MQTT_INGEST_BUFFER_ROWS`, default 256, max 4096) for at most `OPENFDD_MAX_MQTT_BUILDING_BUFFERS` buildings (default 32). MQTTS is archived; there is no MQTTS ingest buffer on the product path, and no ingest buffer may act as a second telemetry store.

Listing datasets (`note_catalog_list`) does not open a session. A hub with hundreds of packages must not keep hundreds of in-memory tables resident. Current code paints Overview from the cached parquet partition (known gap); the target is the PostgreSQL result store or bounded memory.

## Acceptance

Historical acceptance for the known-gap Parquet cache. The Wave P2 replacement keeps the freshness and session criteria and drops the on-disk Parquet layout.

- On-disk layout and schema above.
- `cache_hit_does_not_recompute_and_records_elapsed` shows a second call does not recompute and records `elapsed_ms`.
- `watermark_advance_is_stale_until_refresh` serves stale rows until `refresh: true`.
- Session tests in `fdd_store` cover idle eviction, capacity, MQTT buffer, and `finish_job` clearing `historian_resident`.
- `watermark_ignores_equipment_id_text_and_id_prefixes` rejects `equipment_id=` text and a longer `building_id` prefix.

## Compliance (Soft-OPEN, not FQ)

| Rule | This change |
| --- | --- |
| No `equipment_id` substring filters | Hive keys are exact: path segment `building_id={caller}` or `building={caller}`, or directory key `building` after one `=`. `equipment_id` text is never searched with `contains`, `starts_with`, or `LIKE`. Request `equipment_ids` are a config-hash input only. |
| No building hardcodes; `building_id` is always a parameter | Product cache, session, and retention take the caller id. Missing id skips the cache. No default site. Tests use `site-a`. |
| No MQTT CELL/DELTA | Historical (MQTTS archived): ingest recorded a row-count buffer under the envelope site id. No new topic mode. |
| Timescale/PostgreSQL only | **Not met.** The Parquet cache is a known gap being removed in Wave P2. |
| Building-agnostic session, cache, and retention | Same limits and layout for every building. `OPENFDD_TEST_DEPLOY` is an env flag, not a site-name branch. |
| No VERSION bump / not FQ | Workspace `VERSION` is unchanged. Edge disk proof is still open. |
