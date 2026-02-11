---
title: Equipment
parent: Concepts
nav_order: 2
---

# Equipment

Equipment represents physical devices or systems (AHUs, VAVs, heat pumps, weather stations). Points may belong to equipment.

---

## Structure

| Field | Description |
|-------|-------------|
| `id` | UUID primary key |
| `site_id` | FK to sites |
| `name` | Display name (e.g. "AHU-7") |
| `equipment_type` | Optional type string |
| `external_id` | Optional raw identifier from source |

---

## Hierarchy

```
Site
 └── Equipment (AHU, VAV, etc.)
      └── Points (sensors, setpoints)
```

---

## API

- `GET /equipment` — List equipment (filter by site)
- `GET /equipment/{id}` — Get one
- `POST /equipment` — Create
- `PUT /equipment/{id}` — Update
- `DELETE /equipment/{id}` — Delete
