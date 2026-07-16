---
title: Rule Cookbook
parent: DataFusion SQL Rules
nav_order: 0
has_children: true
permalink: /rules/cookbook/
---

# HVAC FDD Rule Cookbook

Open-source, **standards-first** fault detection for commercial HVAC. Rules use generic semantic variables / Haystack roles (`discharge-air-temp`, `outside-air-temp`, `fan-cmd`, …) — portable across modeled sites and generic BAS telemetry.

**Validated catalog:** **59 rules** from the vibe19 Streamlit-tested pandas catalog. IDs below are canonical.

## Two cookbooks — parity target

| Cookbook | Runtime | Use when |
|----------|---------|----------|
| [**DataFusion SQL**](datafusion-sql-cookbook.html) | **Open-FDD edge** | Live historian, `/sql-fdd`, API `test-sql`, confirmation engine |
| [**Pandas**](pandas-cookbook.html) | **Outside Open-FDD** | CSV exports, notebooks, RCx, parity checks, public benchmarks |

Every **validated** rule exists in **both** cookbooks. Rolling / multi-sensor screens (e.g. `SV-RATE`, `PID-HUNT-1`) ship a **simplified SQL** variant with an explicit caveat — full logic is Pandas-validated. See the [parity matrix](parity-matrix.html).

## Framework

| Doc | Description |
|-----|-------------|
| [**P0 rule catalog**](p0-rule-catalog.html) | Full metadata for every validated rule |
| [Public taxonomy](taxonomy.html) | Equipment classes, rule families, severity |
| [Rule schema](rule-schema.html) | Declarative metadata — compiles to SQL + Pandas |
| [Gap matrix](gap-matrix.html) | Coverage vs ASHRAE GL36, Berkeley, PNNL, NIST |
| [Parity matrix](parity-matrix.html) | SQL ↔ Pandas audit |
| [Roadmap](roadmap.html) | Priority-ranked expansion |
| [Prerequisite macros](prerequisite-macros.html) | Occupancy, fan proven, override / operational gates |
| [Benchmark strategy](benchmark-strategy.html) | Fixtures + regression (`scripts/cookbook_parity_check.py`) |
| [Doc template](doc-template.html) | Standard per-rule documentation |

## Rule inventory (validated)

| Family | Count | Examples |
|--------|------:|----------|
| Sensor validation (sweep) | 5 | SV-RANGE, SV-FLATLINE, SV-SPIKE, SV-STALE, SV-RATE |
| Control hunting | 1 | PID-HUNT-1 |
| Air handling / economizer | 31 | FC1–FC15, ECON-1–7, OAT-METEO, VLV-1, DMP-1, CMD-1 |
| VAV terminals | 7 | VAV-1, VAV-3–5, VAV-7, VAV-REHEAT, VAV-AHU-LEAVE |
| Central plant / CW | 8 | CHW-1–4, CHW-NOLOAD-1, CW-APR-1, CW-FAN-1, CW-OPT-1 |
| Heat pump | 1 | HP-1 |
| Weather | 1 | WX-1 |
| Trim & respond | 3 | TRIM-1, TRIM-3, TRIM-4 |
| Schedule | 2 | SCHED-1, SCHED-247 |

**Total validated:** 59. **Default confirmation:** 300 s (5 min) unless noted per rule.

Additional rules documented under **Not yet in validated catalog** remain in the cookbooks for continuity (flagged, not Streamlit-parity-tested).

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
