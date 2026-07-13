---
title: Rule Cookbook
parent: DataFusion SQL Rules
nav_order: 0
has_children: true
permalink: /rules/cookbook/
---

# HVAC FDD Rule Cookbook

Open-source, **standards-first** fault detection for commercial HVAC. Rules use generic semantic variables (`sat`, `oat`, `fan_cmd`, …) — portable across Haystack-modeled sites and generic BAS telemetry.

## Two cookbooks — exact parity target

| Cookbook | Runtime | Use when |
|----------|---------|----------|
| [**DataFusion SQL**](datafusion-sql-cookbook.html) | **Open-FDD edge** | Live historian, `/sql-fdd`, API `test-sql`, confirmation engine |
| [**Pandas**](pandas-cookbook.html) | **Outside Open-FDD** | CSV exports, notebooks, RCx, parity checks, public benchmarks |

Every rule exists in **both** backends. See the [parity matrix](parity-matrix.html).

## Framework

| Doc | Description |
|-----|-------------|
| [**P0 rule catalog**](p0-rule-catalog.html) | Full metadata for every shipped rule |
| [Public taxonomy](taxonomy.html) | Equipment classes, rule families, severity |
| [Rule schema](rule-schema.html) | Declarative metadata — compiles to SQL + Pandas |
| [Gap matrix](gap-matrix.html) | Coverage vs ASHRAE GL36, Berkeley, PNNL, NIST |
| [Parity matrix](parity-matrix.html) | SQL ↔ Pandas audit |
| [**Operational gates**](operational-gates.html) | RUN / CONDITIONAL / ALWAYS · `SKIPPED_EQUIPMENT_OFF` |
| [**Sensor rate profiles**](sensor-rate-profiles.html) | SV-SLEW research · OFF/STARTUP/STEADY · profile defaults |
| [**PID-HUNT-1**](pid-hunt-1.html) | Generic control-output total-variation hunting (51st rule) |
| [Roadmap](roadmap.html) | Priority-ranked expansion |
| [Prerequisite macros](prerequisite-macros.html) | Occupancy, fan proven, reset, override guards |
| [Benchmark strategy](benchmark-strategy.html) | Fixtures + regression (`scripts/cookbook_parity_check.py`) |
| [Doc template](doc-template.html) | Standard per-rule documentation |

## Rule inventory (summary)

| Family | Count | Examples |
|--------|------:|----------|
| Sensor validation | 8+ | SV-1–SV-7 cookbook + `SV-SLEW` / `SV-SPIKE` registry |
| AHU GL36 (FC1–FC15) | 15 | Duct static, MAT envelope, PID hunting (FC4 mode transitions) |
| VAV terminals | 7 | Comfort, reheat, damper, airflow bias, min flow |
| Economizer / ventilation | 7+ | ECON-1–5, OA-1–2, [diagnostics guide](datafusion-sql-cookbook.html#ahu-economizer-diagnostics-guide) |
| Central plant | 6 | CHW ΔT, DP, reset, tower approach |
| Extended v2 | 12 | Reset, schedule, override, cmd/status, leakage |
| Extended P2 | 6 | VAV-6/7, TOWER-1, CTRL-2, SV-7, OA-2 |
| Trim & respond | 4 | GL36 advisory |
| Heat pump / weather | 3 | HP-1, WX-1–2 |
| Generic control output | 1 | **PID-HUNT-1** total-variation hunting (51st) |

**Total:** 60+ rules with catalog metadata, plus **PID-HUNT-1** as the independently useful 51st FD rule. **Default confirmation:** 300 s (5 min).

**Maintainer rule:** expression cookbooks are **never reduced** — add rules and gates; do not delete FC4, CTRL-2, or other sections.

## Quick start

1. **Assignments** — bind driver points → Haystack → FDD inputs ([modeling guide]({{ site.baseurl }}/modeling/assignments.html))
2. **Plots** — confirm historian columns
3. **SQL FDD Rules** — paste SQL, test with `confirmation_seconds: 300`, activate (integrator)
4. **Pandas parity** — export same window, run matching [Pandas section](pandas-cookbook.html)

## API quick test

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"<SELECT ... fault_raw>","confirmation_seconds":300}' | jq '.ok, .engine'
```

## Safety (edge)

- **SELECT only** — DDL/DML rejected
- Every rule exposes **`fault_raw`** (boolean)
- Integrator JWT required to **activate** rules
- Thresholds are **defaults** — always site-adjustable
