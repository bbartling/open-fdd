---
title: Gap matrix
parent: Rule Cookbook
nav_order: 5
---

# Gap matrix — cookbook vs public literature

Comparison of **Open-FDD cookbook coverage** against public FDD, re-tuning, and commissioning literature. Updated **2026-07-16** (vibe19 validated catalog sync).

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented in validated catalog (Pandas + SQL cookbook) |
| 🚩 | Documented, not yet in validated catalog |
| 🔲 | Backlog |

---

## Coverage summary

| Literature theme | Status |
|------------------|--------|
| GL36 AFDD FC1–FC15 | ✅ |
| Sensor validation (bounds, flatline, ROC, stale, rate) | ✅ SV-RANGE / FLATLINE / SPIKE / STALE / RATE |
| Control hunting | ✅ PID-HUNT-1 (+ FC4) |
| Economizer & ventilation | ✅ ECON-1–7, OA-1, OAT-METEO, MECH-OAT-1 |
| VAV terminals | ✅ VAV-1/3/4/5/7, VAV-REHEAT, VAV-AHU-LEAVE · 🚩 VAV-2/6 |
| Reset / schedule / override | ✅ SCHED-1, SCHED-247 · 🚩 RESET-1, OVR-1, SP-HIGH/LOW, PLANT-1 |
| Command vs status | ✅ CMD-1 |
| Valve / damper leakage | ✅ VLV-1, DMP-1, FC14–15 |
| Plant performance | ✅ CHW-1–4, CHW-NOLOAD-1, CW-APR-1, CW-FAN-1, CW-OPT-1 · 🚩 TOWER-1 |
| Trim & respond advisory | ✅ TRIM-1/3/4 · 🚩 TRIM-2, KPI-1 |
| Weather | ✅ WX-1 · 🚩 WX-2 |
| CI cookbook integrity | ✅ `scripts/cookbook_parity_check.py` |

---

## P3 gaps (future)

| Theme | Notes |
|-------|-------|
| Lead-lag staging | Pattern library |
| Waterside economizer | Site-specific |
| Heat recovery wheel | Site-specific |
| ML / anomaly detection | Out of scope — deterministic SQL/Pandas |

See [roadmap](roadmap.html) and [P0 catalog](p0-rule-catalog.html).
