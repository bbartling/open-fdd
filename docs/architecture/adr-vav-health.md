---
title: VAV health matrix
parent: Architecture
nav_order: 12
permalink: /architecture/adr-vav-health.html
---

# VAV health matrix

A **building-scoped cohort score** for VAV / zone terminals — not a single cookbook rule. Overview and RCx use it to rank boxes that need attention.

## Three dimensions (each PASS / FAIL / unknown)

| Dimension | Question | Typical inputs |
|-----------|----------|----------------|
| **Broken box** | Did confirmed terminal FDD rules fire (VAV-3/4/5/7, reheat, AHU-leave, …)? | FDD results + mapped roles |
| **Comfort** | Is occupied zone temperature outside the comfort band? | `zone_t` + occupancy (same band as VAV-1 / SCHED-1) |
| **Rogue damper** | Is the damper essentially full-open while air should be serving? | Damper % on an **operating** denominator (occupied + air-on) |

Scores render as `3/3` … `0/3`, or `?/3` when evidence is insufficient. **Unknown is not a pass.**

## How to read it

- Prefer **weekly** windows with decent coverage; overnight fan-off should not invent rogue dampers.
- Full-open prevalence is a **starvation / tracking** screen — it does not by itself prove a stuck actuator.
- Missing package roles → empty or `?/3` cells. Fix the map; do not invent points in product code.

## Where it runs

| Surface | API / UI |
|---------|----------|
| Product | `POST /api/analytics/vav-health` (requires `building_id`; mixed-site refused) |
| Overview / RCx | Health matrix + `vav_health_matrix` plot preset |
| Oracle (PyPI) | `open_fdd.analytics.vav_health` for notebooks |

Related: [Rule Cookbook]({{ site.baseurl }}/rules/) · [RCx plot examples]({{ site.baseurl }}/web-app/rcx-plots-by-hvac.html) · [Package authoring](https://github.com/bbartling/open-fdd/blob/master/docs/agent/PACKAGE_AUTHORING.md)
