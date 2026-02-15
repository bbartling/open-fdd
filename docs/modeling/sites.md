---
title: Sites
parent: Data modeling
nav_order: 2
---

# Sites

Sites represent buildings or facilities. Equipment and points are scoped to a site.

---

## Structure

| Field | Description |
|-------|-------------|
| `id` | UUID primary key |
| `name` | Display name |

---

## Scoping

All time-series and equipment queries can be filtered by `site_id`. Grafana dashboards typically scope by site.

---

## API

- `GET /sites` — List sites
- `GET /sites/{id}` — Get one
- `POST /sites` — Create
- `PATCH /sites/{id}` — Update
- `DELETE /sites/{id}` — Delete (cascades to equipment, points, timeseries, fault results; see [Danger zone](howto/danger_zone))
