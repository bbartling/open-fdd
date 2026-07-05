---
title: Rule roadmap
parent: Rule Cookbook
nav_order: 7
---

# Priority-ranked rule roadmap

Implementation order for expanding the public Open-FDD cookbooks. Priorities derive from **public literature frequency** (ASHRAE GL36 AFDD, Berkeley fault taxonomy, PNNL AIRCx, NIST Cx).

## P0 — shipped ✅

- FC1–FC15 (GL36-aligned AHU supervisory)
- SV-1–SV-6 sensor validation
- VAV-1–4, ECON-1–5, CHW-1–4, HP-1, WX-1–2, TRIM-1–4
- AHU auxiliary patterns
- Framework docs + [P0 rule catalog](p0-rule-catalog.html)

## P1 — v2 expansion ✅

RESET-1, SCHED-1, OVR-1, CMD-1, OA-1, VLV-1, DMP-1, VAV-5, PLANT-1, SP-HIGH/LOW, KPI-1 (advisory)

## P2 — shipped ✅

| Rule ID | Description |
|---------|-------------|
| VAV-6 | Reheat when cooling available |
| VAV-7 | Minimum airflow violation |
| TOWER-1 | Cooling tower approach high |
| CTRL-2 | Generic loop hunting (duct static) |
| SV-7 | Wrong-units heuristic |
| OA-2 | DCV minimum OA not met |

## P3 — next quarter

- Lead-lag staging anomalies
- Waterside economizer
- Heat recovery wheel effectiveness
- Site-level demand spike vs weather
- Full FC2–FC15 inline metadata tables (catalog complete today)

---

## Documentation milestones

| Milestone | Status |
|-----------|--------|
| Canonical taxonomy | ✅ |
| Declarative schema | ✅ |
| Gap + parity matrices | ✅ |
| Prerequisite macros | ✅ |
| Doc template | ✅ |
| P0 rule catalog (all metadata) | ✅ |
| CI parity fixtures | ✅ `scripts/cookbook_parity_check.py` |
| Full Pandas v2 + P2 ports | ✅ |
| `docs/agent/` excluded from Pages | ✅ repo-only dev prompts |

---

## Non-goals

- Vendor-specific rule IDs or threshold bundles
- Hardcoded device instance numbers or IP addresses
- Proprietary RCx workbook clones
- Rules requiring ML models (keep deterministic SQL/Pandas)
