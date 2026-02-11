---
title: Sites
parent: Concepts
nav_order: 3
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
- `PUT /sites/{id}` — Update
- `DELETE /sites/{id}` — Delete
