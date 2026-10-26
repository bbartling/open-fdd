# Analytics / RCx / fault result cache

> Storage mandate: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([`openfdd_agent_spec/DATA_CONTRACT.md` § Storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)). Derived FDD / analytics results persist in PostgreSQL or bounded memory. Parquet, Arrow, Arrow IPC, Feather and DataFusion are prohibited in product storage, caching, execution and dependencies.

Derived result rows for `/api/analytics/*` (including RCx presets and sensor-fault analytics) live in the PostgreSQL table `analytics_result`, next to the Timescale historian. They are recomputable output, not telemetry. The cache never writes files. It is not the AFDD `{rule_id}.json` blob under rule results.

## Storage

Table `analytics_result` (`sql/schema/02_openfdd_dims.sql`, columns added forward-only by `sql/schema/08_analytics_result_cache.sql`):

| Column | Meaning |
| --- | --- |
| `building_id`, `query_id`, `query_version`, `window_key`, `config_hash` | Primary key. `window_key` is `{start}__{end}` (`open` when unbounded). |
| `window_start`, `window_end` | The two window tokens. |
| `result_contract`, `sql_pack`, `model_revision` | Computation identity. Also folded into `config_hash`. |
| `watermark_source`, `watermark_status`, `watermark_order`, `watermark_utc`, `coverage` | Scoped Timescale input the envelope was computed from. |
| `generated_at`, `engine`, `result_query_version` | Envelope metadata. |
| `payload` | `jsonb` with `rows`, `equipment`, `points`, `skipped`, `warnings`, `coverage`. Explicit JSON nulls stay on the object that set them. |
| `updated_at` | Last write. Used for the per-building row cap. |

`cache.schema` on responses is `analytics-result-postgres-v1`. That storage name is not the result contract.

Each building keeps at most `OPENFDD_ANALYTICS_CACHE_MAX_ROWS` rows (default 2000, ceiling 100000). A write trims that building's oldest rows by `updated_at` in the same transaction. Other buildings are not touched.

Without a configured Timescale historian (`OPENFDD_DATABASE_URL` / `OPENFDD_HISTORIAN=timescale`) the cache is skipped and the envelope is computed uncached (`cache.skipped: true`). There is no file fallback.

`building_id` is a request parameter. Empty or unsafe ids (`/`, `\`, `..`, NUL) skip the cache and compute uncached. Request `equipment_ids` are sorted into the config hash. They are not a `LIKE` / prefix / contains filter. This cache does not infer `equipType`. Tenant isolation: the caller `building_id` is part of the key and `read_tenant_id` is part of the config hash, so two tenants never share a row.

## Freshness

The cache key includes the result contract (`analytics-result-contract-v2`), the analytics SQL pack content hash plus the FDD pack fingerprint, and the site model revision (equipment stamps, role map, and point map).

Freshness uses the scoped Timescale sample watermark and coverage for the request window: sample count, valued count, distinct series, min and max timestamps, and the value sum. Named equipment is an exact key-token match. A failed or unreadable watermark read is `watermark_status: unavailable` and is never a fresh hit (`stale: true` when a prior envelope is served).

| Condition | Behavior |
| --- | --- |
| No row, or version/config/contract/pack/model differs | Miss. Compute, upsert the row, `cache.hit=false`. |
| Row has no contract, pack, model, or known watermark | Incompatible. Recompute. Do not serve it as fresh. |
| Same identity and the same known watermark and coverage | Hit. Do not recompute. |
| Same identity, known watermark or coverage moved | `stale: true` on the JSON body and `cache.stale`. Default serves the last rows. |
| Watermark or model read failed | Not a hit. Default serves the last compatible rows with `stale: true` and `watermark_status: unavailable`. |
| `refresh: true` on the request | Always recompute. A failed watermark read still reports `stale: true`. |
| `OPENFDD_ANALYTICS_CACHE_ON_STALE=recompute` | Watermark advance recomputes instead of serving stale. |

Rows written before `08_analytics_result_cache.sql` carry empty stamps and are incompatible, so they recompute on first use.

Stale is a structured flag. It is not copied into envelope `warnings`, so Overview does not grow a cache caption.

Routine opens omit `refresh` and use the cache. Explicit operator actions send `refresh: true`: Overview **Update analytics** / **Force refresh analytics** (including the health, weather, and SQL-anomaly sections whose token advanced), a rules-updated refetch of those sections, and **Refresh RCx preset**. Opening a building or an RCx preset does not.

`elapsed_ms` on `cache` is the server time for that read or recompute (hit vs miss).

Fuel bill math (`/api/analytics/fuel`) is not this cache. The global faults summary is not stored under a building id. Sensor-fault analytics (`sensor-faults-v1`) is the fault result table.

## Legacy Parquet cache files (manual cleanup)

Earlier releases wrote `analytics_results/…/results.parquet` (`analytics-result-parquet-v2`) under the local file root (`OPENFDD_ANALYTICS_CACHE_ROOT`, else `OPENFDD_STORAGE_URL`, else the hub root). Central no longer reads or writes them. They are derived data and central does not delete them automatically. To reclaim the space after upgrading, stop central and remove the directory by hand, for example:

```bash
# inside the central volume; adjust to your OPENFDD_STORAGE_URL root
rm -rf /workspace/openfdd/analytics_results
```

Removing it does not touch historian samples, `fdd_run`, or labeled rule-result files. Rollback to an earlier image simply recomputes; it does not need those files.

## Building RAM

CSV / package buildings are guests.

- First analytics query opens an interactive lease (default **2** concurrent, clamp 1–8, `OPENFDD_MAX_BUILDING_SESSIONS`).
- The historian working set is marked loaded only for the compute job. `finish_job` clears it when the result row is written (or the job returns). The lease stays until leave or idle so the active building remains the warm slot.
- Idle default **60s**, clamp 30–120 (`OPENFDD_BUILDING_SESSION_IDLE_SECS`). A timer in central evicts idle CSV leases.
- A third CSV guest evicts the oldest idle CSV lease. If every interactive slot is inside a running job, the API returns **429**.
- `POST /api/sessions/building/leave` with `{ "building_id" }` drops that lease. The SPA calls it when `?site=` changes.
- `GET /api/sessions/buildings` (hub admin) lists `interactive_slots`, `historian_resident`, and `ram_resident`.

`ram_resident` / `historian_resident` are the RSS check. After unload they must not still name the CSV building. The lease list can still name it until leave or idle.

**Historical, superseded by the Timescale-only mandate:** live MQTTS ingest once recorded a capped row buffer (`OPENFDD_MQTT_INGEST_BUFFER_ROWS`, default 256, max 4096) for at most `OPENFDD_MAX_MQTT_BUILDING_BUFFERS` buildings (default 32). MQTTS is archived; there is no MQTTS ingest buffer on the product path, and no ingest buffer may act as a second telemetry store.

Listing datasets (`note_catalog_list`) does not open a session. A hub with hundreds of packages must not keep hundreds of in-memory tables resident.

## Acceptance

- `cache_hit_does_not_recompute_and_records_elapsed` shows a second call does not recompute and records `elapsed_ms`.
- `watermark_advance_is_stale_until_refresh` serves stale rows until `refresh: true`.
- `tenants_do_not_share_a_cache_hit` and `postgres_store_round_trips_isolates_buildings_and_trims` cover isolation and the row cap (the latter runs when `OPENFDD_TEST_DATABASE_URL` is set).
- Session tests in `fdd_store` cover idle eviction, capacity, and `finish_job` clearing `historian_resident`.

## Compliance (Soft-OPEN, not FQ)

| Rule | This change |
| --- | --- |
| No `equipment_id` substring filters | Lookups are exact primary-key equality. Request `equipment_ids` are a config-hash input only. |
| No building hardcodes; `building_id` is always a parameter | Cache, session, and trim take the caller id. Missing id skips the cache. Tests use `site-a`. |
| No MQTT CELL/DELTA | Historical (MQTTS archived): ingest recorded a row-count buffer under the envelope site id. No new topic mode. |
| Timescale/PostgreSQL only | No Parquet, Arrow, or file writes on this path. |
| Building-agnostic session and cache | Same limits for every building. `OPENFDD_TEST_DEPLOY` is an env flag, not a site-name branch. |
| No VERSION bump / not FQ | Workspace `VERSION` is unchanged. |
