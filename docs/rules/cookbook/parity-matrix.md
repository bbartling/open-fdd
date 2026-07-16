---
title: Parity matrix
parent: Rule Cookbook
nav_order: 6
---

# SQL ↔ Pandas parity matrix

**Audit date:** 2026-07-16 · **Validated catalog:** 59 vibe19 rules · **Target:** zero silent drift

## Summary

| Status | Count |
|--------|------:|
| Full parity (SQL + Pandas, same ID) | 54 |
| Pandas-complete / SQL simplified | 5 |
| Documented but not in validated catalog | 13 |

**SQL-simplified (intentional):** `SV-RATE`, `PID-HUNT-1`, `FC4`, `SV-SPIKE`, `SV-FLATLINE` — rolling / multi-sensor logic is fully validated in Pandas; SQL ships a screening variant with an explicit caveat in the SQL cookbook.

---

## Family coverage

| Family | Validated IDs | SQL | Pandas |
|--------|---------------|:---:|:------:|
| sensor | SV-RANGE, SV-FLATLINE, SV-SPIKE, SV-STALE, SV-RATE | ✅* | ✅ |
| control | PID-HUNT-1 | ✅* | ✅ |
| ahu | FC1–FC15, AHU-*, ECON-1–7, OAT-METEO, MECH-OAT-1, CMD-1, OA-1, VLV-1, DMP-1 | ✅ | ✅ |
| vav | VAV-1, VAV-3–5, VAV-7, VAV-REHEAT, VAV-AHU-LEAVE | ✅ | ✅ |
| plant | CHW-1–4, CHW-NOLOAD-1, CW-APR-1, CW-FAN-1, CW-OPT-1 | ✅ | ✅ |
| heatpump | HP-1 | ✅ | ✅ |
| weather | WX-1 | ✅ | ✅ |
| trim | TRIM-1, TRIM-3, TRIM-4 | ✅ | ✅ |
| schedule | SCHED-1, SCHED-247 | ✅ | ✅ |

\* simplified SQL variant

---

## Backend-specific caveats

| Topic | DataFusion SQL | Pandas |
|-------|----------------|--------|
| Window / rolling | `LAG()`, limited `OVER` | `.shift()`, `.rolling()`, multi-sensor sweeps |
| Confirmation | API `confirmation_seconds` | `confirm_fault()` |
| Sensor sweeps | Per-column CASE examples | Catalog `sensor_sweep=True` across all roles |
| Control hunting | Screening thresholds | Full TV / reversal / cycle metrics (`PID-HUNT-1`) |

---

## Parity test procedure

1. Export `telemetry_pivot` window from edge historian
2. Run SQL via `POST /api/fdd-rules/{id}/test-sql`
3. Run matching Pandas mask offline (vibe19 catalog compute)
4. Run fixture suite: `scripts/cookbook_parity_check.py --all`

See [benchmark strategy](benchmark-strategy.html).
