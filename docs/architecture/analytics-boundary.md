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
- RCx / analytics: still largely `services/ui/app/analytics.py` + `rcx_plots.py` (pandas) — migrate per audit inventory

No arbitrary operator SQL editor. Integrator SQL lab (if any) is separate and gated.
