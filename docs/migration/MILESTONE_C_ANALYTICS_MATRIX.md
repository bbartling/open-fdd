---
title: Milestone C analytics matrix
parent: Migration
nav_order: 22
---

# Milestone C analytics matrix

**Date:** 2026-07-28 · Branch `milestone-c/c1-c2-analytics-runtime`

Production analytics move family-by-family into central typed APIs under
`/api/analytics/*`. Responses use `AnalyticsEnvelope` (no Plotly JSON).
Oracle pandas paths in `open_fdd.analytics` / Vibe 19 remain for parity.

## Engine honesty

| Field | Value |
|-------|-------|
| Current `engine` | `central-analytics-v1` |
| Meaning | Pure Rust algorithms in `services/central/src/analytics/` (Arrow-ready) |
| Follow-up | Wire DataFusion SQL / MemTable per family; bump engine label only when SQL path is live |

Do **not** label envelopes `engine: datafusion` until a family actually executes via DataFusion.

## Families

| Family | Source (pandas oracle) | Central API | `query_version` | Impl status | Fixture / parity | UI cutover | Retirement |
|--------|------------------------|-------------|-----------------|-------------|------------------|------------|------------|
| Runtime | `open_fdd.analytics.runtime_intervals` + motor rollups | `POST /api/analytics/runtime` | `runtime-v1` | **Compute live** (Δt integration + gap clip; inline `samples`) | Unit tests in `runtime.rs` | Partial Streamlit wire | After full Overview cutover |
| Sensor health | `sensor_health_matrix` | `POST /api/analytics/sensor-health` | `sensor-health-v1` | **Minimal compute** (coverage, flatline, missingness, min/max/mean) | Unit tests in `sensor_health.rs` | Pending | — |
| Schedule / comfort | occupancy helpers | `POST /api/analytics/schedule` | `schedule-v1` | **Minimal compute** (occupied hours + after-hours fan hours) | Unit tests in `schedule.rs` | Pending | — |
| Mechanical cooling | `mech_cooling_*` | `POST /api/analytics/mechanical-cooling` | `mechanical-cooling-v1` | **Minimal compute** (evidence hierarchy; pump/valve ≠ compressor) | Unit tests in `mechanical_cooling.rs` | Pending | — |
| Economizer diagnostics | `economizer_free_cooling_diagnostics` | `POST /api/analytics/economizer` | `economizer-diagnostics-v1` | **Compute live** (fan-on, ΔT gate, OA frac, MAT resid; inline `series`) | Unit tests in `economizer.rs` | Partial Streamlit wire | After cutover |
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

Historian / job Feather load and DataFusion SQL MemTable are the next wiring
steps after these contracts. Closeout / acceptance:
[`MILESTONE_C_CLOSEOUT.md`](MILESTONE_C_CLOSEOUT.md),
[`MILESTONE_C_ACCEPTANCE.md`](MILESTONE_C_ACCEPTANCE.md).
Rule parity: [`MILESTONE_C_RULE_PARITY.md`](MILESTONE_C_RULE_PARITY.md).
Benchmarks: [`../benchmarks/MILESTONE_C_ANALYTICS.md`](../benchmarks/MILESTONE_C_ANALYTICS.md).

## Related

- [Pandas usage inventory](../architecture/PANDAS_USAGE_INVENTORY.md)
- [Analytics boundary](../architecture/analytics-boundary.md)
- [DataFusion-first](../architecture/datafusion-first.md)
