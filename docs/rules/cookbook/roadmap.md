---
title: Rule roadmap
parent: Rule Cookbook
nav_order: 7
---

# Priority-ranked rule roadmap

Implementation order for expanding the public Open-FDD cookbooks. Priorities derive from **public literature frequency** (ASHRAE GL36 AFDD, Berkeley fault taxonomy, PNNL AIRCx, NIST Cx), not private workbooks.

## P0 — shipped (maintain parity)

- FC1–FC15 (GL36-aligned AHU supervisory)
- SV-1–SV-6 sensor validation
- VAV-1–4, ECON-1–5, CHW-1–4, HP-1, WX-1–2, TRIM-1–4
- AHU auxiliary patterns (SAT deviation, duct static, heat/cool simultaneous, fan-off warm duct)
- Prerequisite macro library (v2)
- Framework docs: taxonomy, schema, gap/parity matrices, benchmark strategy

## P1 — v2 expansion (this release)

| Rank | Rule ID | Rationale (public literature) |
|------|---------|----------------------------|
| 1 | RESET-1 | SAT/OAT reset missing — top RCx / AIRCx finding |
| 2 | SCHED-1 | Unoccupied runtime — energy + schedule audit staple |
| 3 | OVR-1 | Persistent override — PNNL re-tuning, Cx |
| 4 | CMD-1 | Command/status mismatch — NIST Cx, Berkeley taxonomy |
| 5 | OA-1 | Low ventilation / OA fraction — GL36 ventilation intent |
| 6 | VLV-1 | Valve leakage when commanded closed — coil ΔT patterns extend FC14–15 |
| 7 | DMP-1 | OA damper leakage — economizer fault family |
| 8 | VAV-5 | Airflow sensor bias — terminal FDD literature |
| 9 | PLANT-1 | CHW DP reset missing — plant re-tuning |
| 10 | SP-HIGH / SP-LOW | Occupied setpoint drift |
| 11 | KPI-1 | Performance KPI advisory scoring |

## P2 — next quarter

- VAV-6 reheat with cooling available
- VAV-7 minimum airflow violation
- TOWER-1 cooling tower approach
- CTRL-2 generic loop hunting (non-SAT)
- SV-7 wrong-units heuristic
- DCV minimum OA (OA-2)

## P3 — pattern library

- Lead-lag staging anomalies
- Waterside economizer
- Heat recovery wheel effectiveness
- Site-level demand spike vs weather

---

## Documentation milestones

| Milestone | Status |
|-----------|--------|
| Canonical taxonomy | ✅ [taxonomy.md](taxonomy.html) |
| Declarative schema | ✅ [rule-schema.md](rule-schema.html) |
| Gap + parity matrices | ✅ |
| Prerequisite macros | ✅ [prerequisite-macros.md](prerequisite-macros.html) |
| Doc template per rule | ✅ [doc-template.md](doc-template.html) |
| Public benchmark harness | ✅ [benchmark-strategy.md](benchmark-strategy.html) |
| Full metadata on all P0 rules | In progress |
| CI parity regression | Planned — synthetic fixtures in repo |

---

## Non-goals

- Vendor-specific rule IDs or threshold bundles
- Hardcoded device instance numbers or IP addresses
- Proprietary RCx workbook clones
- Rules requiring ML models (keep deterministic SQL/Pandas)
