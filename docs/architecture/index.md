---
title: Architecture
layout: default
nav_order: 3
has_children: true
permalink: /architecture/
---

# Architecture

Open-FDD is a **container stack** (central / React SPA / fieldbus / mqtt / mcp) with Arrow historian, DataFusion SQL FDD, and Project Haystack semantic model.

| Topic | Document |
|-------|----------|
| [ADR — VAV health matrix](adr-vav-health.html) | Cohort analytic (not a 60th rule) |
| [Services](services.html) | Stack images and compose roles |
| [Data flow](data-flow.html) | Drivers → model → historian → FDD → UI |
| [Storage & DataFusion](storage-and-datafusion.html) | Feather historian and SQL rules |
| [DataFusion-first](datafusion-first.html) | Product DF SQL contract (no product pandas FDD) |
| [Job workspaces](job-workspaces.html) | Persistent analysis Jobs under `workspace/jobs/` |
| [Analytics boundary](analytics-boundary.html) | Typed DF analytics vs React |
| [Compute boundary ownership](compute_boundary_ownership.html) | Product vs PyPI/oracle vs historical paths |

Modernization ledgers: [React / Rust migration](../migration/react-rust/).
