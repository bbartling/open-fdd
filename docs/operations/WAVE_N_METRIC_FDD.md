---
title: Metric and mixed units FDD
parent: Operations
nav_order: 19
nav_exclude: true

---

# Metric / mixed units FDD (Wave N)

Open-FDD SQL FDD is **°F canonical** in the registry. Metric CSVs and BACnet eng units convert at query via `unit_system=metric|si`.

Wave N uses ACME Trane VAV BACnet values (often °C) to validate metric fault equations while imperial sites (`BUILDING_100`) remain °F on the same multi-tenant hub.

## Agent checks

1. Confirm BACnet object units on polled ZN-T / setpoints (do not invent).
2. Run Lab / FDD with `unit_system=metric` against ACME; imperial against BUILDING_100.
3. Record evidence in [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md) row **wave-n-metric-fdd**.

Cookbook dual expression: `docs/rules/cookbook/` (SQL + pandas stay aligned).
