---
title: Rule Cookbook
parent: DataFusion SQL Rules
nav_order: 0
has_children: true
permalink: /rules/cookbook/
---

# HVAC FDD Rule Cookbook

Production-ready supervisory fault detection patterns for **any BACnet/Haystack site**. Rules bind to **semantic FDD inputs** from your assignment graph — never hardcode one building's device instance or private IP in product code.

## Two cookbooks (same physics, different runtimes)

| Cookbook | Runtime | Use when |
|----------|---------|----------|
| [**DataFusion SQL**](datafusion-sql-cookbook.html) | **Open-FDD edge** (Rust) | Live historian, `/sql-fdd` tab, API `test-sql`, confirmation engine |
| [**Pandas**](pandas-cookbook.html) | **Outside Open-FDD** | CSV exports, notebooks, RCx studies, parity checks, training |

Open-FDD **3.3+** executes FDD with **DataFusion SQL only** on the edge. Pandas is **not** bundled in the GHCR image — this community cookbook helps analysts who still work in notebooks or compare against legacy workflows.

## Start here

| Guide | Content |
|-------|---------|
| [DataFusion SQL cookbook](datafusion-sql-cookbook.html) | **Primary** — copy-paste SQL for `telemetry_pivot`, GL36 AHU, economizer, plants |
| [Pandas cookbook](pandas-cookbook.html) | Parallel patterns for offline analysis |
| [Fault confirmation](fault-confirmation.html) | `confirmation_seconds`, debouncing, poll intervals |
| [Sensor validation](sensor-validation.html) | Bounds, flatline, rate-of-change, mixing envelope |
| [GL36 AHU rules A–M](gl36-ahu-rules.html) | ASHRAE Guideline 36–style reference table |
| [Central plants](central-plants.html) | CHW, CTW, boiler, low-ΔT |
| [Windowing & debugging](windowing-debugging.html) | Lookback, nulls, test workflow |
| [Haystack → SQL columns](haystack-assignments.html) | How Brick/Haystack IDs become `telemetry_pivot` columns |
| [GL36 algorithm stubs](gl36-algorithm-stubs.html) | Trim/respond & plant-enable advisory SQL |
| [Legacy expression migration](legacy-expression-migration.html) | YAML/NumPy → SQL/Pandas mapping |

## Dashboard workflow

1. **Assignments** — bind driver points → Haystack → FDD inputs ([modeling guide]({{ site.baseurl }}/modeling/assignments.html))
2. **Plots** — confirm historian rows and column names
3. **SQL FDD Rules** (`/sql-fdd`) — paste SQL, **Format SQL**, **Test**, then **Activate** (integrator)
4. **Validation** (`/live-fdd-validation`) — end-to-end BACnet → historian → SQL → fault overlay

## API quick test

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"<SELECT ... fault_raw>","confirmation_seconds":300}' | jq '.ok, .engine'
```

## Safety (edge)

- **SELECT only** — DDL/DML rejected
- Every rule must expose **`fault_raw`** (boolean) for the confirmation engine
- Integrator JWT required to **activate** rules

## Legacy Python / PyArrow

The pre-3.2 Python edge used PyArrow `apply_faults_arrow` modules. That path is archived; use **DataFusion SQL** on the Rust edge or **Pandas** off-edge. Content from the legacy `rule-cookbook/` tree is ported here as SQL + Pandas equivalents.
