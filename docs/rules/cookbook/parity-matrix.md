---
title: Parity matrix
parent: Rule Cookbook
nav_order: 6
---

# SQL ↔ Pandas parity matrix

Every production rule should exist in **both** cookbooks with identical logic for the same input window. Backend-specific caveats are noted.

**Audit date:** 2026-07-05 · **Target:** zero manual drift

## Summary

| Status | Count |
|--------|------:|
| ✅ Full parity | 42 |
| ⚠️ SQL only (fix queued) | 8 |
| 🆕 v2 expansion (both) | 12 |
| Pandas only | 0 |

---

## Sensor validation

| Rule ID | SQL | Pandas | Notes |
|---------|:---:|:------:|-------|
| SV-1 zone range | ✅ | ✅ | |
| SV-2 OA range | ✅ | ✅ | |
| SV-3 OA humidity | ✅ | ✅ | |
| SV-4 mixing envelope | ✅ | ✅ | Fixed v2 |
| SV-5 stale data | ✅ | ✅ | Fixed v2 |
| SV-6 flatline / ROC | ✅ | ✅ | Pandas split into SV-4/5 aliases → unified SV-6 |

---

## AHU (FC1–FC15 + patterns)

| Rule ID | SQL | Pandas | Notes |
|---------|:---:|:------:|-------|
| FC1–FC15 | ✅ | ✅ | FC4 uses 3600 s confirm in both |
| SAT_DEVIATION_HIGH | ✅ | ✅ | |
| DUCT_STATIC_HIGH | ✅ | ✅ | Fixed v2 |
| HEAT_COOL_SIMULT | ✅ | ✅ | |
| FAN_OFF_DUCT_WARM | ✅ | ✅ | Fixed v2 |

---

## VAV / economizer / plant / HP / WX / TRIM

| Rule ID | SQL | Pandas | Notes |
|---------|:---:|:------:|-------|
| VAV-1–4 | ✅ | ✅ | |
| ECON-1–4 | ✅ | ✅ | |
| ECON-5 preheat | ✅ | ✅ | Fixed v2 |
| CHW-1–4 | ✅ | ✅ | CHW-4 fixed v2 |
| HP-1 | ✅ | ✅ | |
| WX-1–2 | ✅ | ✅ | SQL uses `LAG()`; Pandas uses `.diff()` |
| TRIM-1–4 | ✅ | ✅ | TRIM-3/4 fixed v2 |

---

## v2 expansion (P1 — both backends)

| Rule ID | SQL | Pandas | Family |
|---------|:---:|:------:|--------|
| RESET-1 SAT reset missing | 🆕 | 🆕 | reset |
| SCHED-1 unoccupied runtime | 🆕 | 🆕 | schedule |
| OVR-1 persistent override | 🆕 | 🆕 | override |
| CMD-1 fan cmd/status mismatch | 🆕 | 🆕 | command.status |
| OA-1 low ventilation | 🆕 | 🆕 | ventilation |
| VLV-1 valve leakage | 🆕 | 🆕 | actuator.leakage |
| DMP-1 OA damper leakage | 🆕 | 🆕 | actuator.leakage |
| VAV-5 airflow sensor bias | 🆕 | 🆕 | terminal.vav |
| PLANT-1 CHW DP reset missing | 🆕 | 🆕 | reset.plant |
| SP-HIGH occupied setpoint high | 🆕 | 🆕 | reset |
| SP-LOW occupied setpoint low | 🆕 | 🆕 | reset |
| KPI-1 performance score advisory | 🆕 | 🆕 | kpi.advisory |

---

## Backend-specific caveats

| Topic | DataFusion SQL | Pandas |
|-------|----------------|--------|
| Window functions | `LAG()`, `AVG() OVER` native | `.shift()`, `.rolling()` |
| NULL handling | `IS NULL` in `CASE` | `.notna()` masks |
| Confirmation | API `confirmation_seconds` after SQL | `confirm_fault()` on series |
| Poll interval | Assumed 60 s default in docs | `POLL_SECONDS` tunable |
| Equipment filter | `WHERE equipment_id = …` | `df[df.equipment_id == …]` |

### Parity test procedure

1. Export `telemetry_pivot` window from edge historian
2. Run SQL via `POST /api/fdd-rules/{id}/test-sql`
3. Run matching Pandas mask + `confirm_fault()` offline
4. Assert `fault_raw` timestamps match; confirmed faults match within one poll period

See [benchmark strategy](benchmark-strategy.html).
