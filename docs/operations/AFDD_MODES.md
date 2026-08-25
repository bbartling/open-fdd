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
OPENFDD_AFDD_INTERVAL_MINUTES=180
OPENFDD_AFDD_LOOKBACK_VALUE=3
OPENFDD_AFDD_LOOKBACK_UNIT=days
```

Lookback bounds are passed as `start_utc` / `end_utc` on the registry run and applied as DataFusion predicates on `history` (and `weather` when present) so Apache partition/stats pruning stays effective.

## Local == cloud

Same GHCR central image and SQL path. Only storage env changes (`OPENFDD_PARQUET_ROOT` / volume vs `OPENFDD_STORAGE_URL=s3://…`). No Railway/AWS-specific SQL fork.

## Low-RAM labs

```text
OPENFDD_QUERY_MEMORY_MB=256
OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill
```

Prefer lookback-bounded continuous cycles over full-history scans on small hosts.

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
