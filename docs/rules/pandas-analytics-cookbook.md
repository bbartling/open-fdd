---
title: Pandas analytics cookbook
parent: Rule Cookbook
nav_order: 5
permalink: /rules/pandas-analytics-cookbook/
---

# Pandas analytics cookbook

Analytics inputs and outputs use SI canonical units. Source-point units are engineer-declared and normalized once by the Timescale writer; analytics SQL/pandas consume SI-normalized frames and do not perform query-time unit admission. Display conversion belongs to presentation. See [unit contract]({{ site.baseurl }}/modeling/units/).


**Oracle / third-party only** — `open_fdd.analytics` / related PyPI helpers. Not the product request path.

| Use | Notes |
|-----|-------|
| Notebooks / CSV studies | Mirror Overview / RCx math offline |
| Parity | Compare to `sql/analytics` SQL pack |
| Product | Timescale SQL via `/api/analytics/*` |

FDD oracle rules stay in the [Pandas cookbook](cookbook/pandas-cookbook.html). Soft-OPEN ≠ FQ.
