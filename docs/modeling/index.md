---
title: Data modeling
nav_order: 7
has_children: true
---

# Data modeling

The Open-FDD data model is built around **sites**, **equipment**, and **points**: the same entities you create, read, update, and delete via the API (**CRUD** = Create, Read, Update, Delete). The REST API (Swagger at `/docs`) and the data-model endpoints (`/data-model/export`, `/data-model/import`, `/data-model/ttl`) are the main way to manage this data. The database is the single source of truth; the Brick TTL file is regenerated on every change so FDD rules and Grafana stay in sync.

**Concepts (entities):**

- **[Sites](modeling/sites)** — Buildings or facilities. All equipment and points are scoped to a site.
- **[Equipment](modeling/equipment)** — Physical devices (AHUs, VAVs, heat pumps). Belong to a site; have points.
- **[Points](modeling/points)** — Time-series references (sensors, setpoints). Link to equipment and site; store `external_id`, optional `brick_type` and `rule_input` for FDD.

**Framework:** CRUD is provided by the FastAPI REST API. The data-model API adds bulk export/import and Brick TTL generation; see [Overview](modeling/overview) for the flow (DB → TTL → FDD column_map) and [API Reference — Platform REST API](api/platform) for all endpoints.
