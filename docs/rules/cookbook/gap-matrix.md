---
title: Gap matrix
parent: Rule Cookbook
nav_order: 5
---

# Gap matrix — cookbook vs public literature

Comparison of **Open-FDD cookbook coverage** against public FDD, re-tuning, and commissioning literature. Updated 2026-07-05 (Phase 2a/2b complete).

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented in both SQL + Pandas with catalog metadata |
| 🔲 | P3 backlog |

---

## Coverage summary

| Literature theme | Status |
|------------------|--------|
| GL36 AFDD FC1–FC15 | ✅ |
| Sensor validation (bounds, flatline, ROC, mixing, stale, wrong-units) | ✅ SV-1–SV-7 |
| Economizer & ventilation | ✅ ECON-1–5, OA-1–2 |
| VAV terminals | ✅ VAV-1–7 |
| Reset / schedule / override | ✅ RESET-1, SCHED-1, OVR-1, SP-HIGH/LOW, PLANT-1 |
| Command vs status | ✅ CMD-1 |
| Valve / damper leakage | ✅ VLV-1, DMP-1, FC14–15 |
| Plant performance | ✅ CHW-1–4, TOWER-1, PLANT-1 |
| Control hunting | ✅ FC4 (mode transitions), CTRL-2 (process PV), **PID-HUNT-1** (output total variation) |
| Trim & respond advisory | ✅ TRIM-1–4, KPI-1 |
| CI parity fixtures | ✅ |

---

## P3 gaps (future)

| Theme | Notes |
|-------|-------|
| Lead-lag staging | Pattern library |
| Waterside economizer | Site-specific |
| Heat recovery wheel | Site-specific |
| ML / anomaly detection | Out of scope — deterministic rules only |

See [roadmap](roadmap.html) and [P0 catalog](p0-rule-catalog.html).
