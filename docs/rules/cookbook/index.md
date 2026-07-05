---
title: Rule Cookbook
parent: DataFusion SQL Rules
nav_order: 0
has_children: true
permalink: /rules/cookbook/
---

# HVAC FDD Rule Cookbook

Open-source, **standards-first** fault detection for commercial HVAC. Rules use generic semantic variables (`sat`, `oat`, `fan_cmd`, …) — portable across Haystack-modeled sites and generic BAS telemetry. No vendor-specific namespaces.

## Two cookbooks — exact parity target

| Cookbook | Runtime | Use when |
|----------|---------|----------|
| [**DataFusion SQL**](datafusion-sql-cookbook.html) | **Open-FDD edge** | Live historian, `/sql-fdd`, API `test-sql`, confirmation engine |
| [**Pandas**](pandas-cookbook.html) | **Outside Open-FDD** | CSV exports, notebooks, RCx, parity checks, public benchmarks |

Every rule exists in **both** backends. See the [parity matrix](parity-matrix.html).

## Framework (v2)

| Doc | Description |
|-----|-------------|
| [Public taxonomy](taxonomy.html) | Equipment classes, rule families, severity |
| [Rule schema](rule-schema.html) | Declarative metadata — compiles to SQL + Pandas |
| [Gap matrix](gap-matrix.html) | Coverage vs ASHRAE GL36, Berkeley, PNNL, NIST |
| [Parity matrix](parity-matrix.html) | SQL ↔ Pandas audit |
| [Roadmap](roadmap.html) | Priority-ranked missing families |
| [Prerequisite macros](prerequisite-macros.html) | Occupancy, fan proven, reset, override guards |
| [Benchmark strategy](benchmark-strategy.html) | Public datasets & regression scenarios |
| [Doc template](doc-template.html) | Standard per-rule documentation |

## Rule inventory (summary)

| Family | Count | Examples |
|--------|------:|----------|
| Sensor validation | 6 | SV-1–SV-6 bounds, flatline, mixing |
| AHU GL36 (FC1–FC15) | 15 | Duct static, MAT envelope, PID hunting |
| VAV terminals | 5 | Comfort, reheat, damper, airflow bias |
| Economizer / ventilation | 6 | ECON-1–5, OA-1 |
| Central plant | 5 | CHW ΔT, DP, reset, flow |
| Extended v2 | 12 | Reset, schedule, override, cmd/status, leakage |
| Trim & respond | 4 | GL36 advisory |
| Heat pump / weather | 3 | HP-1, WX-1–2 |

**Total:** 50+ rules with metadata. **Default confirmation:** 300 s (5 min).

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

## Public literature anchors

ASHRAE Guideline 36 AFDD addenda · Berkeley Lab fault taxonomy · PNNL AIRCx · NIST HVAC-Cx · Project Haystack · [DataFusion SQL](https://datafusion.apache.org/) · Pandas rolling windows
