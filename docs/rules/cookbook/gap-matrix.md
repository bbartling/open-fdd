---
title: Gap matrix
parent: Rule Cookbook
nav_order: 5
---

# Gap matrix — cookbook vs public literature

Comparison of **current Open-FDD cookbook coverage** against common opportunities in public FDD, re-tuning, and commissioning literature. Gaps drive the [roadmap](roadmap.html). No proprietary rule names or threshold bundles are used.

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented in both SQL + Pandas (P0) |
| ⚠️ | Partial — one backend or missing metadata/scenarios |
| 🔲 | Planned P1/P2 — draft in v2 expansion |
| — | Out of scope (site-specific hardware) |

---

## Airside (AHU / RTU)

| Public literature theme | Cookbook today | Gap / next |
|-------------------------|----------------|------------|
| GL36 AFDD Rules A–M (FC1–FC15) | ✅ FC1–FC15 | Add full metadata blocks + validation scenarios |
| Duct static high / low | ✅ FC1, DUCT_STATIC_HIGH | — |
| MAT mixing envelope | ✅ FC2–FC3, SV mixing | — |
| PID / control hunting | ✅ FC4 | Generic CTRL hunting for non-SAT loops 🔲 |
| SAT tracking / deviation | ✅ FC5–FC13, SAT_DEVIATION | — |
| Simultaneous heat + cool | ✅ HEAT_COOL_SIMULT | — |
| Economizer faults | ✅ ECON-1–4, FC6–FC11 | ECON-5 preheat ✅ SQL only → fix parity |
| Low ventilation / OA fraction | ✅ ECON-4, FC6 | DCV minimum OA 🔲 |
| SAT reset missing | 🔲 RESET-1 | **P1 — draft in v2** |
| Setpoint too high / low | ⚠️ partial (comfort bands) | Occupied SP drift 🔲 |
| Unoccupied runtime | 🔲 SCHED-1 | **P1 — draft in v2** |
| Persistent override | 🔲 OVR-1 | **P1 — draft in v2** |
| Command vs status (fan) | 🔲 CMD-1 | **P1 — draft in v2** |
| Valve leakage (coils) | ⚠️ FC14–FC15 inactive ΔT | Dedicated VLV-1 🔲 |
| Damper leakage (OA) | 🔲 DMP-1 | **P1 — draft in v2** |
| Trim & respond advisory | ✅ TRIM-1–4 | KPI scoring layer 🔲 |

---

## Terminals (VAV / FCU)

| Theme | Cookbook | Gap |
|-------|----------|-----|
| Zone comfort band | ✅ VAV-1 | — |
| Night setback | ✅ VAV-2 | — |
| Excessive reheat | ✅ VAV-3 | — |
| Damper stuck open | ✅ VAV-4 | — |
| Airflow sensor bias | 🔲 VAV-5 | **P1 — draft in v2** |
| Reheat with cooling available | 🔲 VAV-6 | P2 |
| Minimum airflow violation | 🔲 VAV-7 | P2 |

---

## Central plant

| Theme | Cookbook | Gap |
|-------|----------|-----|
| Low CHW ΔT | ✅ CHW-1 | — |
| DP below SP at max pump | ✅ CHW-2 | — |
| Supply temp deadband | ✅ CHW-3 | — |
| High flow at max pump | ✅ CHW-4 | Pandas parity ⚠️ |
| CHW DP reset missing | 🔲 PLANT-1 | **P1 — draft in v2** |
| Tower approach high | 🔲 TOWER-1 | P2 |
| Staging / lead-lag | 🔲 PLANT-2 | P3 |

---

## Sensor quality

| Theme | Cookbook | Gap |
|-------|----------|-----|
| Out of range | ✅ SV-1–3 | — |
| Mixing envelope | ✅ SQL SV-4 | Pandas ⚠️ |
| Stale data | ✅ SQL SV-5 | Pandas ⚠️ |
| Flatline | ✅ SV-6 / Pandas SV-4 | Align IDs |
| Rate of change | ✅ SV-6 / Pandas SV-5 | Align IDs |
| Wrong units detection | 🔲 SV-7 | P2 — validation scenario only |

---

## Cross-cutting macros (literature-common)

| Macro | Status |
|-------|--------|
| Occupancy state | 🔲 → [prerequisite macros](prerequisite-macros.html) |
| Fan/pump proven on | 🔲 |
| Mode delay / startup suppression | 🔲 |
| Steady-state window | 🔲 |
| Reset-enabled check | 🔲 |
| Override suppression | 🔲 |
| Sensor quality gating | ⚠️ partial in SV rules |

---

## Parity drift (audit 2026-07-05)

Rules in **SQL only** (fix in this release): SV mixing envelope, SV stale, CHW-4, ECON-5, TRIM-3, TRIM-4, DUCT_STATIC_HIGH, FAN_OFF_DUCT_WARM.

Rules in **Pandas only**: none (Pandas is strict subset).

See [parity matrix](parity-matrix.html) for rule-by-rule status.
