---
title: VAV health matrix v1
parent: Architecture
nav_order: 40
---

# ADR — `vav_health_matrix_v1`

VAV Health is a **cohort analytic**, not a cookbook diagnostic. Catalog remains **62 pandas + 4 SQL analytics = 66**.

## Three independent dimensions

| Dimension | Meaning | Unknown when |
| --- | --- | --- |
| Broken box | Confirmed VAV-3/4/5/7/REHEAT/AHU-LEAVE (configurable) | No FDD results / missing roles |
| Comfort | Occupied zone temperature outside the same band as VAV-1 / SCHED-1 / Overview | Missing occupancy or `zone_t` |
| Rogue damper | Damper ≥ 0.975 on a **proven operating** denominator (occupied + air-on preferred) | Fan-off overnight, coverage or hours below default |

Unknown is **not PASS**. Score labels: `3/3` … `0/3` and `?/3` (insufficient).

## Rogue vs failed actuator

Full-open prevalence (≥95% of ≥20 operating hours, ≥80% coverage, weekly defaults) is a **starvation / tracking** screen. It does **not** by itself prove a stuck actuator.

## Engines

Pandas (`open_fdd.analytics.vav_health`) is the oracle library. Rust/DataFusion serves `POST /api/analytics/vav-health` **scoped by `building_id`**. Mixed-site queries are refused.
