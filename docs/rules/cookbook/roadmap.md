---
title: Rule roadmap
parent: Rule Cookbook
nav_order: 7
---

# Priority-ranked rule roadmap

Implementation order for expanding the public Open-FDD cookbooks. Priorities derive from **public literature frequency** (ASHRAE GL36 AFDD, Berkeley fault taxonomy, PNNL AIRCx, NIST Cx) and the **validated vibe19 catalog**.

## P0 — validated pandas catalog ✅ (62 rules)

Production Open-FDD SQL registry is **66** rules (`sql_rules/registry.yaml`). The **62** figure is the pandas oracle catalog floor (see [parity matrix](parity-matrix.html)).

- Sensor sweeps: SV-RANGE, SV-FLATLINE, SV-SPIKE, SV-STALE, SV-RATE
- Control: PID-HUNT-1
- AHU GL36 FC1–FC15 + AHU-SATDEV / AHU-DUCTHI / AHU-SIMUL
- Economizer / OA: ECON-1–7, OA-1, OAT-METEO, MECH-OAT-1, VLV-1, DMP-1, CMD-1
- VAV: VAV-1 through VAV-7, VAV-REHEAT, VAV-AHU-LEAVE
- RESET-1
- Plant / CW: CHW-1–4, CHW-NOLOAD-1, CW-APR-1, CW-FAN-1, CW-OPT-1
- HP-1, WX-1, TRIM-1/3/4, SCHED-1, SCHED-247
- Framework docs + [P0 rule catalog](p0-rule-catalog.html)

## Next — promote into validated catalog

| Rule ID | Description |
|---------|-------------|
| TOWER-1 | Cooling tower approach high |
| CTRL-2 | Generic loop hunting |
| OVR-1 | Persistent override |
| OA-2 | DCV minimum OA |
| PLANT-1 | CHW DP reset missing |
| SP-HIGH / SP-LOW | Occupied SP drift |
| TRIM-2 / KPI-1 / WX-2 | Advisory / weather consistency |

## Later

- Lead-lag staging anomalies
- Waterside economizer
- Heat recovery wheel effectiveness
- Site-level demand spike vs weather

---

## Documentation milestones

| Milestone | Status |
|-----------|--------|
| Canonical taxonomy | ✅ |
| Declarative schema | ✅ |
| Gap + parity matrices | ✅ |
| Prerequisite macros | ✅ |
| Doc template | ✅ |
| P0 rule catalog (validated metadata) | ✅ |
| CI cookbook integrity + fixtures | ✅ `scripts/cookbook_parity_check.py` |
| vibe19 ID sync (Pandas + SQL) | ✅ 2026-07-16 |

---

## Non-goals

- Vendor-specific rule IDs or threshold bundles
- Hardcoded device instance numbers or IP addresses
- Proprietary RCx workbook clones
- Rules requiring ML models (keep deterministic SQL/Pandas)
