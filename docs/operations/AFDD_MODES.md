# AFDD operating modes (bulk vs continuous)

Open-FDD uses **one** Timescale / PostgreSQL SQL registry (`sql/fdd`) for fault detection ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md)). Soft-OPEN ≠ FQ. **AFDD** is how and when that registry runs — not a second rule engine. Storage mandate: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing**; Parquet, Arrow, Arrow IPC, Feather and DataFusion are prohibited in product storage, caching, execution and dependencies ([`DATA_CONTRACT.md` § Storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)). AFDD results persist in PostgreSQL or bounded memory.

| | Bulk / manual “run all” | Continuous AFDD |
|--|-------------------------|-----------------|
| Typical data | CSV / package import (bulk RCx — full history, not the AFDD timer) | NF portal hourly append (MQTT live append is historical) |
| Trigger | Operator, soak, or `POST /api/fdd/run` | Timer + optional `POST /api/afdd/scheduler/run-now` |
| Default | `OPENFDD_AFDD_MODE=bulk` (no timer) | Opt-in `continuous` |
| Isolation | Explicit `building_id` | Per-`building_id` mutex + checkpoint |
| Window | Full imported building history | Rolling lookback ending at live telemetry watermark |

**Rule:** bulk CSV import never implicitly enables recurring AFDD. A historian flush / commit does not run FDD by itself.

## Multi-site / Jobs

Historian and FDD scope by **`building_id`**. Switching Jobs in the UI must not pause NF portal ingest or continuous AFDD on other buildings. Continuous AFDD can keep cycling on one portal site while an operator imports synthetic CSV and runs bulk FDD on another building.

### Continuous scope (env)

When `OPENFDD_AFDD_MODE=continuous`, central resolves which buildings the timer runs:

| Env | Behavior |
| --- | --- |
| `OPENFDD_AFDD_BUILDING_ID` unset and `OPENFDD_AFDD_BUILDING_IDS` empty | **All NF provider sites:** one registry run per configured portal site in `OPENFDD_PROVIDER_SITES` / `state.providers.sites`. CSV package buildings are **not** scheduled (use bulk `POST /api/fdd/run`). |
| `OPENFDD_AFDD_BUILDING_ID=<id>` | Single provider site when the list env is empty. |
| `OPENFDD_AFDD_BUILDING_IDS=a,b,c` | Explicit comma-separated subset of **provider** sites (wins over single id). CSV-only building ids fail at startup. Non-provider ids fail with a clear error. |

Each scheduled provider site keeps its **own watermark and checkpoint**, so a slow site does not block others. The timer evaluates the rolling lookback in **bounded time chunks** (`OPENFDD_AFDD_CHUNK_HOURS`, default 1 hour). The cycle record stores the full lookback window plus `chunk_seconds`; chunk `fdd_run` rows tile that window on `window_start` / `window_end` with no gaps. `GET /api/afdd/status` (alias `/api/afdd/scheduler/status`) lists every scheduled provider site with `cycle_window_start`, `cycle_window_end`, `chunk_seconds`, checkpoint, and last result summary.

Compose forwards `OPENFDD_AFDD_*` and ingest tuning vars from repo-root `.env` through `docker/compose.local.yml` (see [`LOCAL_DEPLOYMENT.md`](LOCAL_DEPLOYMENT.md)).

## SkySpark-like continuous (opt-in)

```text
OPENFDD_AFDD_MODE=continuous
OPENFDD_AFDD_SCHEDULE=interval
OPENFDD_AFDD_INTERVAL_MINUTES=180
OPENFDD_AFDD_LOOKBACK_VALUE=3
OPENFDD_AFDD_LOOKBACK_UNIT=days
```

`OPENFDD_AFDD_SCHEDULE=wall_clock` pins the run to a local time instead of `last_completed_at + interval`:

```text
OPENFDD_AFDD_SCHEDULE=wall_clock
OPENFDD_AFDD_WALL_CLOCK_HHMM=05:00
OPENFDD_AFDD_WALL_CLOCK_TIMEZONE=America/Chicago
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
```

The timezone is an operator IANA name. `America/Chicago` is the lab recipe so the cycle can finish before a 06:00 digest. It is not a product default and it is not a building id. The analysis window still ends at the latest persisted telemetry watermark (`start = end − lookback`). A missed day while the process is down is one lookback-sized cycle (`catch_up`), not one full-history pass per missed day.

Lookback bounds are passed as `start` and `end` on the registry run payload (UTC) and applied as SQL window filters on Timescale `history` (and `weather` when present). The result write upserts only that window. **`run_fdd_registry` persists runs to PostgreSQL** (`fdd_run`, `fdd_interval_result`, `fdd_incremental_checkpoint`); `/api/fdd/results` reads those tables. Legacy `{rule_id}.json` manifests under the workspace rule-results tree are not written on the Timescale path and may be removed manually after verification ([`LOCAL_HOSTING.md`](LOCAL_HOSTING.md)). Slices outside the AFDD window stay unchanged where windowed slice metadata exists (`rows_sha256` on `GET /api/afdd/scheduler/result-slices`). There is no scheduler "update all". If the existing result file is missing, the window is the first slice. If it cannot be read or parsed, the publish fails and the file is left unchanged.

`lookback_equals_schedule_cadence` on scheduler status is true when the configured lookback duration equals the schedule cadence in seconds: 24h for wall-clock, or `interval_minutes` for interval mode. A 3-hour interval with a 3-day lookback stays valid and reports false. Downtime does not stretch the window.

Operator UI / `POST /api/afdd/scheduler/config` allowlist: schedule `interval` or `wall_clock`; interval **1 / 3 / 6 / 12 / 24 hours** (`60…1440` minutes); lookback **1 / 2 / 3 days**; wall clock requires `HH:MM` plus an IANA timezone. `update_all` / `lookback=all` is rejected. Mode stays env-owned. A persisted `state/afdd/scheduler-runtime-config.json` overlay overwrites interval/lookback/schedule on boot — clear it when pinning env lookback in **hours**.

`POST /api/afdd/scheduler/backfill` re-runs an explicit `start_utc`/`end_utc` (max 366 days, max 64 chunks). It does not move the continuous checkpoint. Bulk `POST /api/fdd/run` without a window remains the imported-package registry scan; it is not the timer.

## ACME = continuous AFDD qualification building (local stack)

Live OT tenant **ACME** is the field proof for continuous AFDD (not Synthetic-59 flood / gate 19).

```text
OPENFDD_AFDD_MODE=continuous
OPENFDD_AFDD_INTERVAL_MINUTES=1440
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
OPENFDD_AFDD_BUILDING_ID=ACME
```

- **Cadence:** either `OPENFDD_AFDD_INTERVAL_MINUTES=1440` (checkpoint + interval) or `OPENFDD_AFDD_SCHEDULE=wall_clock` at `05:00` `America/Chicago`. Interval 1440 does not pin the clock. Wall-clock does. The live hub stays on interval until this build is the field tip.
- **Ops clock (lab):** daily **05:00 America/Chicago**, lookback 24h / 1 day, so the cycle can finish before the **06:00** digest. That timezone is operator config for the lab, not a hardcoded site.
- **Window:** lookback-sized only. `end` = latest persisted telemetry watermark; `start` = `end − lookback` (`plan_continuous_cycle`). Result rows outside that window are left unchanged (`merge_windowed_rule_result`). A rows-only file and a null-bound `preserved_unscoped` slice keep the same rows hash. After downtime, catch-up is still one lookback-sized window (`catch_up`). Historical rebuild is `POST /api/afdd/scheduler/backfill` with an explicit range (`plan_bounded_backfill`), never an update-all flag.
- Soft-OPEN ACME/local stack: Timescale-only, dual-write false, **no site backups** unless Ben asks ([TIMESCALE_WAVE_X.md](TIMESCALE_WAVE_X.md)).
- Stress SoT: gate **38** `38_acme_afdd_qualification.sh` (MEGA required). Gate **19** remains synth flood only.
- **RAM (portable):** Prefer lookback-bounded SQL cycles on small hosts. Watch `/api/health.memory_budget` when present — not host-hardcoded 10/24 GB in product code. Legacy DataFusion spill pool vars (`OPENFDD_DATAFUSION_SPILL_DIR`, FairSpillPool) are historical and prohibited on the product path ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md)); do not set them.

## Local == cloud

Same GHCR central image and Timescale SQL path. Storage env is `OPENFDD_DATABASE_URL` / `OPENFDD_HISTORIAN=timescale`. No host-specific SQL fork. Soft-OPEN ≠ FQ.

## Low-RAM labs

```text
# Prefer lookback-bounded continuous cycles on small hosts.
OPENFDD_COMPUTE_MAX_INFLIGHT=2
OPENFDD_MEMORY_SHED_FRACTION=0.75
OPENFDD_MEMORY_ABORT_FRACTION=0.85
```

Prefer lookback-bounded continuous cycles over full-history scans on small hosts. AFDD run-now is **chunked** (time × equipment) with cooperative cancel (`partial` / `cancelled`).

### Memory pressure policy (#1127 / #1179)

Heavy analytics/AFDD **shed** new work at `OPENFDD_MEMORY_SHED_FRACTION` (default **0.75 × hard**) with HTTP 503 + `security_audit{event:"memory_shed"}`; **abort** in-flight heavy work at `OPENFDD_MEMORY_ABORT_FRACTION` (default **0.85**). A per-request **in-flight sampler** (`OPENFDD_MEMORY_SAMPLE_MS`, default **1000**) polls cgroup `memory.current` during analytics/SQL/AFDD chunks and sets the cancel flag before the kernel OOMs; `/api/health.memory_budget` reports `sample_ms` and `last_trip` when present. Unlimited Docker cgroups use host **MemTotal** as the portable hard limit (`source=host_meminfo`). **Run-now** uses the **building-scoped** historian watermark (not the global live watermark); empty scoped windows return `status=no_data` quickly (#1192). Light paths (health, auth, ingest ack) never shed on memory alone — health stays **200** with `memory_budget.shed_state`. Ingest/control stay preferred; a deferred/cancelled AFDD cycle does **not** advance the checkpoint. Live local-stack combined-load qualification remains operator/Grok Soft-OPEN after a GHCR pin — HTTP success alone is not survival proof; require `events` `oom_killed` watch + memory series.

### Lab ops (this Soft-OPEN program)

- **No backups** unless Ben asks. Soft-OPEN local stack/ACME = Timescale-only, dual-write false. Data continuity = keep Timescale / historian volumes across `compose pull` + `up -d` (never `-v`).
- Docker maintenance before pulls: prune unused images/digests; **never** `docker volume prune` / `compose down -v` / delete `workspace/`.

## Feather / Parquet dual-write

**Forbidden.** Timescale is the sole product historian ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md)). NF portal REST, NF LAN gRPC (per-site `transport`) and CSV share one validated, idempotent Timescale telemetry writer. Do not add a Feather / Parquet / Arrow hot tier, raw-data mirror, or legacy fallback for lookback, speed, or migration. AFDD and bulk FDD **results** belong in PostgreSQL (`fdd_run`, …) and bounded memory — not parallel manifest JSON stores.

## Suspend telemetry (per site/edge)

Operator-facing pause for non-paying / maintenance sites:

| Keep | Stop |
|------|------|
| Hosted BACnet server | BACnet client poll |
| Fieldbus process | Weather fetch |
| Ability to resume | MQTT telemetry publish (spool flush gated) |

- Fieldbus REST: `GET /telemetry/status`, `POST /telemetry/suspend`, `POST /telemetry/resume`
- MQTT command: `target_id=edge:telemetry` with `value.action` = `suspend`|`resume` (protocol `mixed` via Central `POST /api/commands`)
- Desired state persists on the edge (`OPENFDD_TELEMETRY_STATE_PATH`)
- Combined nightly gate exercises suspend → server still up → resume before synth bulk

## UI revision

SPA sidebar shows `GET /api/health` → `{CARGO_PKG_VERSION}+shortsha`. Each turnkey platform patch should bump the workspace patch version (tiny rev) so operators see a new semver as well as a new SHA after pulling nightly.
