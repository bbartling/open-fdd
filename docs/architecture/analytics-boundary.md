---
title: Analytics boundary
parent: Architecture
nav_order: 12
---

# Analytics boundary

**Status:** target contract (PR2+). Do not scatter ad-hoc SQL through Streamlit.

## Boundary

```text
Streamlit asks → typed service call → DataFusion SQL / views → Arrow → thin UI frame
```

## Domains (planned)

runtime · sensor_health · weather · economizer · comfort · airside · hydronic ·
mechanical_cooling · metering · schedules · equipment · rcx · wattlab_exports

Each domain: typed inputs, params, SQL, Arrow schema, null/unit rules, tests.

## Today

- FDD: `crates/fdd_sql` + `fdd_rules` (production)
- Analytics APIs: `services/central/src/analytics/` + `POST /api/analytics/{runtime,sensor-health,schedule,mechanical-cooling,economizer,rcx/ahu,rcx/vav,metering}`
  - Engine: `central-analytics-v1` (pure Rust; DataFusion SQL wiring next — see [MILESTONE_C_ANALYTICS_MATRIX](../migration/MILESTONE_C_ANALYTICS_MATRIX.md))
  - Runtime + economizer: live compute from inline samples/series; other families schema stubs
- RCx / Overview UI: still largely pandas via `services/ui/app/analytics.py` + `rcx_plots.py` — migrate per matrix

No arbitrary operator SQL editor. Integrator SQL lab (if any) is separate and gated.
