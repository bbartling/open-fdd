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
| Runtime | `open_fdd.analytics.runtime_intervals` + motor rollups | `POST /api/analytics/runtime` | `runtime-v1` | **Compute live** (Δt integration + gap clip; inline `samples`) | Unit tests in `runtime.rs` | Pending Overview cards | After Streamlit typed client |
| Sensor health | `sensor_health_matrix` | `POST /api/analytics/sensor-health` | `sensor-health-v1` | Schema stub | Pending | Pending | — |
| Schedule / comfort | occupancy helpers | `POST /api/analytics/schedule` | `schedule-v1` | Schema stub | Pending | Pending | — |
| Mechanical cooling | `mech_cooling_*` | `POST /api/analytics/mechanical-cooling` | `mechanical-cooling-v1` | Schema stub (evidence hierarchy TBD) | Pending | Pending | — |
| Economizer diagnostics | `economizer_free_cooling_diagnostics` | `POST /api/analytics/economizer` | `economizer-diagnostics-v1` | **Compute live** (fan-on, ΔT gate, OA frac, MAT resid; inline `series`) | Unit tests in `economizer.rs` | Pending RCx/AHU + Overview link | After cutover |
| RCx AHU | `rcx_plots` AHU presets | `POST /api/analytics/rcx/ahu` | `rcx-ahu-v1` | Schema stub | Pending | Pending | — |
| RCx VAV | zone comfort / VAV presets | `POST /api/analytics/rcx/vav` | `rcx-vav-v1` | Schema stub | Pending | Pending | — |
| Metering | `app/metering.py` | `POST /api/analytics/metering` | `metering-v1` | Schema stub | Pending | Pending | — |

## Envelope fields

`schema_version`, `query_version`, `job_id`, `run_id`, `input_fingerprint`,
`generated_at`, `engine`, `coverage`, `warnings`, `rows`, `equipment`,
`points`, `skipped`.

## Request body

`AnalyticsRequest`: query fields (`job_id`, `run_id`, `equipment_ids`, `start`,
`end`, `max_points`, `query_version`) plus optional inline `samples` (runtime)
or `series` (economizer / later families). Optional `max_gap_seconds`, `dt_min_f`.

Historian / job Feather load is the next wiring step after these contracts.

## Related

- [Pandas usage inventory](../architecture/PANDAS_USAGE_INVENTORY.md)
- [Analytics boundary](../architecture/analytics-boundary.md)
- [DataFusion-first](../architecture/datafusion-first.md)
