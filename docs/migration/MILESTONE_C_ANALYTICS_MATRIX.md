---
title: Milestone C analytics matrix
parent: Migration
nav_order: 22
---

# Milestone C analytics matrix

**Date:** 2026-07-28 · Branch `milestone-d/d1-historian-datafusion-runtime`

Production analytics move family-by-family into central typed APIs under
`/api/analytics/*`. Responses use `AnalyticsEnvelope` (no Plotly JSON).
Oracle pandas paths in `open_fdd.analytics` / Vibe 19 remain for parity
(`OPENFDD_ANALYTICS_ORACLE=1` only — no silent UI fallback).

## Engine honesty

| Field | Value |
|-------|-------|
| `central-analytics-v1` ([`CENTRAL_ENGINE`](../../services/central/src/analytics/mod.rs)) | Pure Rust algorithms on **inline** samples/series |
| `datafusion` ([`DF_ENGINE`](../../services/central/src/analytics/mod.rs)) | DataFusion SQL over historian Parquet (`analytics/historian.rs`) |
| Rule | Label `engine: datafusion` **only** when that request executed via DF |

## Historian bridge (D1)

| Item | Status |
|------|--------|
| `OPENFDD_PARQUET_ROOT` / workspace `.cache/parquet` fallbacks | Same as edge FDD registry |
| `try_register_history` → `fdd_sql::register_parquet_tree` | Live |
| Runtime without inline `samples` | Tries DF historian path first (`handle_async`); Δt when `equipment_id` + `timestamp_utc` + `fan_status`/`fan_cmd` exist; else count probe + warning |
| Inline `samples` present | Still `central-analytics-v1` Δt integration |
| React Overview runtime | Central only; pandas weekly only if `OPENFDD_ANALYTICS_ORACLE=1` |

## Families

| Family | Source (pandas oracle) | Central API | `query_version` | Impl status | Fixture / parity | UI cutover | Retirement |
|--------|------------------------|-------------|-----------------|-------------|------------------|------------|------------|
| Runtime | `open_fdd.analytics.runtime_intervals` + motor rollups | `POST /api/analytics/runtime` | `runtime-v1` | **Live** — inline Δt + **historian DF bridge** | Unit tests in `runtime.rs` / `historian.rs` | Overview: no silent pandas | After full Overview cutover |
| Sensor health | `sensor_health_matrix` | `POST /api/analytics/sensor-health` | `sensor-health-v1` | **Minimal compute** (coverage, flatline, missingness, min/max/mean) | Unit tests in `sensor_health.rs` | Pending | — |
| Schedule / comfort | occupancy helpers | `POST /api/analytics/schedule` | `schedule-v1` | **Minimal compute** (occupied hours + after-hours fan hours) | Unit tests in `schedule.rs` | Pending | — |
| Mechanical cooling | `mech_cooling_*` | `POST /api/analytics/mechanical-cooling` | `mechanical-cooling-v1` | **Minimal compute** (evidence hierarchy; pump/valve ≠ compressor) | Unit tests in `mechanical_cooling.rs` | Pending | — |
| Economizer diagnostics | `economizer_free_cooling_diagnostics` | `POST /api/analytics/economizer` | `economizer-diagnostics-v1` | **Compute live** (fan-on, ΔT gate, OA frac, MAT resid; inline `series`) | Unit tests in `economizer.rs` | Partial React wire (no silent pandas) | After cutover |
| RCx AHU | `rcx_plots` AHU presets | `POST /api/analytics/rcx/ahu` | `rcx-ahu-v1` | **Minimal compute** (sat_sp / duct_static_sp coverage stub) | Unit tests in `rcx.rs` | Pending | — |
| RCx VAV | zone comfort / VAV presets | `POST /api/analytics/rcx/vav` | `rcx-vav-v1` | **Minimal compute** (zone_temp vs setpoint ranking) | Unit tests in `rcx.rs` | Pending | — |
| Metering | `app/metering.py` | `POST /api/analytics/metering` | `metering-v1` | **Minimal compute** (monthly kWh sum) | Unit tests in `metering.rs` | Pending | — |

## Envelope fields

`schema_version`, `query_version`, `job_id`, `run_id`, `input_fingerprint`,
`generated_at`, `engine`, `coverage`, `warnings`, `rows`, `equipment`,
`points`, `skipped`.

## Request body

`AnalyticsRequest`: query fields (`job_id`, `run_id`, `equipment_ids`, `start`,
`end`, `max_points`, `query_version`) plus optional inline `samples` (runtime)
or `series` (economizer / later families). Optional `max_gap_seconds`, `dt_min_f`.

Historian Parquet registration for runtime is live (D1); remaining families still
use inline payloads until their DF bridges land. Closeout / acceptance:
[`MILESTONE_C_CLOSEOUT.md`](MILESTONE_C_CLOSEOUT.md),
[`MILESTONE_C_ACCEPTANCE.md`](MILESTONE_C_ACCEPTANCE.md).
Rule parity: [`MILESTONE_C_RULE_PARITY.md`](MILESTONE_C_RULE_PARITY.md).
Benchmarks: [`../benchmarks/MILESTONE_C_ANALYTICS.md`](../benchmarks/MILESTONE_C_ANALYTICS.md).

## Related

- [Pandas usage inventory](../architecture/PANDAS_USAGE_INVENTORY.md)
- [Analytics boundary](../architecture/analytics-boundary.md)
- [DataFusion-first](../architecture/datafusion-first.md)
