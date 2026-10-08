# AFDD operating modes (bulk vs continuous)

Open-FDD uses **one** DataFusion SQL registry for fault detection. **AFDD** is how and when that registry runs — not a second rule engine.

| | Bulk / manual “run all” | Continuous AFDD |
|--|-------------------------|-----------------|
| Typical data | CSV / package import | MQTT live append |
| Trigger | Operator, soak, or `POST /api/fdd/run` | Timer + optional `POST /api/afdd/scheduler/run-now` |
| Default | `OPENFDD_AFDD_MODE=bulk` (no timer) | Opt-in `continuous` |
| Isolation | Explicit `building_id` | Per-`building_id` mutex + checkpoint |
| Window | Full imported building history | Rolling lookback ending at live telemetry watermark |

**Rule:** bulk CSV import never implicitly enables recurring AFDD. A Parquet flush does not run FDD by itself.

## Multi-site / Jobs

Historian and FDD scope by **`building_id`**. Switching Jobs in the UI must not pause MQTT ingest or continuous AFDD on other buildings. Continuous AFDD can keep cycling on an OT site while an operator imports synthetic CSV and runs bulk FDD on another building.

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

Lookback bounds are passed as `start_utc` / `end_utc` on the registry run and applied as DataFusion DataFrame filters on `history` (and `weather` when present) so partition and stats pruning stay on the scan. The result write upserts only that window. Slices outside the window stay unchanged (`rows_sha256` on `GET /api/afdd/scheduler/result-slices`). There is no scheduler "update all". If the existing result file is missing, the window is the first slice. If it cannot be read or parsed, the publish fails and the file is left unchanged.

`lookback_matches_cadence` on scheduler status is true when that lookback equals the cadence: 24h for wall-clock, or `interval_minutes` for interval mode. A 3-hour interval with a 3-day lookback stays valid and reports false. Downtime does not stretch the window.

Operator UI / `POST /api/afdd/scheduler/config` allowlist: schedule `interval` or `wall_clock`; interval **1 / 3 / 6 / 12 / 24 hours** (`60…1440` minutes); lookback **1 / 2 / 3 days**; wall clock requires `HH:MM` plus an IANA timezone. `update_all` / `lookback=all` is rejected. Mode stays env-owned. A persisted `state/afdd/scheduler-runtime-config.json` overlay overwrites interval/lookback/schedule on boot — clear it when pinning env lookback in **hours**.

`POST /api/afdd/scheduler/backfill` re-runs an explicit `start_utc`/`end_utc` (max 366 days, max 64 chunks). It does not move the continuous checkpoint. Bulk `POST /api/fdd/run` without a window remains the imported-package registry scan; it is not the timer.

## ACME = continuous AFDD qualification building (Railway)

Live OT tenant **ACME** is the field proof for continuous AFDD (not Synthetic-59 flood / gate 19).

```text
OPENFDD_AFDD_MODE=continuous
OPENFDD_AFDD_INTERVAL_MINUTES=1440
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
OPENFDD_AFDD_BUILDING_ID=ACME
OPENFDD_PARQUET_FLUSH_SECONDS=300
```

- **Cadence:** either `OPENFDD_AFDD_INTERVAL_MINUTES=1440` (checkpoint + interval) or `OPENFDD_AFDD_SCHEDULE=wall_clock` at `05:00` `America/Chicago`. Interval 1440 does not pin the clock. Wall-clock does. The live hub stays on interval until this build is the field tip.
- **Ops clock (lab):** daily **05:00 America/Chicago**, lookback 24h / 1 day, so the cycle can finish before the **06:00** digest. That timezone is operator config for the lab, not a hardcoded site.
- **Window:** lookback-sized only. `end` = latest persisted telemetry watermark; `start` = `end − lookback` (`plan_continuous_cycle`). Result rows outside that window are left unchanged (`merge_windowed_rule_result`). A rows-only file and a null-bound `preserved_unscoped` slice keep the same rows hash. After downtime, catch-up is still one lookback-sized window (`catch_up`). Historical rebuild is `POST /api/afdd/scheduler/backfill` with an explicit range (`plan_bounded_backfill`), never an update-all flag.
- Compact ACME hive parts before enabling continuous AFDD (`scripts/ops/railway_compact_hub.sh` / hub-admin compaction).
- Stress SoT: gate **38** `38_acme_afdd_qualification.sh` (MEGA required). Gate **19** remains synth flood only.
- **RAM (portable, #1179):** Aggregate DataFusion pool = `(detected cgroup/host hard − reserves) × OPENFDD_COMPUTE_MEMORY_FRACTION` (default **0.50**) as a **FairSpillPool** with spill under `OPENFDD_DATAFUSION_SPILL_DIR` (default `<storage_root>/.datafusion-spill`). `OPENFDD_QUERY_MEMORY_MB` is the **per-request** ceiling (default pool/2), not the process pool. Absolute overrides (`OPENFDD_COMPUTE_MEMORY_MB`) are clamped to `hard − reserves`. Watch `/api/health.memory_budget` `{hard_limit_bytes, pool_bytes, current_bytes, peak_bytes, shed_state}` — not Railway-hardcoded 10/24 GB in product code. Example derived pools: ~3 GiB on 8 GiB edge, ~10 GiB on 24 GiB hub, ~46 GiB on 100 GiB VM (after reserves).

## Local == cloud

Same GHCR central image and SQL path. Only storage env changes (`OPENFDD_PARQUET_ROOT` / volume vs `OPENFDD_STORAGE_URL=s3://…`). No Railway/AWS-specific SQL fork.

## Low-RAM labs

```text
# Prefer fraction defaults; pin absolutes only when measuring a known box.
OPENFDD_COMPUTE_MEMORY_FRACTION=0.50
OPENFDD_QUERY_MEMORY_MB=256
OPENFDD_COMPUTE_MAX_INFLIGHT=2
OPENFDD_MEMORY_SHED_FRACTION=0.75
OPENFDD_MEMORY_ABORT_FRACTION=0.85
OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill
```

Prefer lookback-bounded continuous cycles over full-history scans on small hosts. AFDD run-now is **chunked** (time × equipment) with cooperative cancel (`partial` / `cancelled`).

### Memory pressure policy (#1127 / #1179)

Heavy analytics/AFDD **shed** new work at `OPENFDD_MEMORY_SHED_FRACTION` (default **0.75 × hard**) with HTTP 503 + `security_audit{event:"memory_shed"}`; **abort** in-flight heavy work at `OPENFDD_MEMORY_ABORT_FRACTION` (default **0.85**). Light paths (health, auth, ingest ack) never shed on memory alone — health stays **200** with `memory_budget.shed_state`. Ingest/control stay preferred; a deferred/cancelled AFDD cycle does **not** advance the checkpoint. Live Railway combined-load qualification remains operator/Grok Soft-OPEN after a GHCR pin — HTTP success alone is not survival proof; require `events` `oom_killed` watch + memory series.

### Lab ops (this Soft-OPEN program)

- **No backups** unless Ben asks. Data continuity = keep historian volumes across `compose pull` + `up -d` (never `-v`).
- Docker maintenance before pulls: prune unused images/digests; **never** `docker volume prune` / `compose down -v` / delete `workspace/`.

## Feather

Optional legacy dual-write / interchange only. **Not** the FDD or AFDD source of truth. Do not add a Feather hot tier for lookback. Freeze dual-write until an explicit consumer audit.

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
