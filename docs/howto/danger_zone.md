---
title: Danger zone — when data is purged
parent: How-to Guides
nav_order: 5
---

# Danger zone — when data is purged

This page documents **when database or dashboard data can be deleted** and **how to intentionally purge** it.

---

## What does NOT purge data

**`./scripts/bootstrap.sh`** does **not** wipe the database. It starts containers and runs migrations (idempotent). Your sites, points, timeseries, and fault results remain.

**`./scripts/bootstrap.sh --reset-grafana`** wipes only the **Grafana volume** (dashboards, users, saved state). Database data is unchanged.

---

## CRUD deletes — cascade behavior

When you delete via the API (Swagger or `test_crud_api.py`):

| Delete | Cascades to |
|--------|-------------|
| **Site** | Equipment, points, timeseries_readings, fault_results, fault_events, ingest_jobs |
| **Equipment** | Points (with that equipment_id), timeseries for those points |
| **Point** | timeseries_readings for that point |

`DELETE /sites/{id}`, `DELETE /equipment/{id}`, and `DELETE /points/{id}` remove the entity and all dependent data. This is **permanent**.

---

## Data retention policy

`007_retention.sql` adds TimescaleDB retention: chunks older than **1 year** are dropped from `timeseries_readings`, `fault_results`, `host_metrics`, `container_metrics`. This is automatic; no manual action.

To change retention: edit the `INTERVAL` in `platform/sql/007_retention.sql` and re-apply (or adjust via TimescaleDB functions).

---

## How to purge (intentional wipe)

### Option 1: Drop and recreate the database

**DANGER: All data is lost.**

```bash
cd platform
docker compose exec db psql -U postgres -c "DROP DATABASE openfdd;"
docker compose exec db psql -U postgres -c "CREATE DATABASE openfdd;"
# Re-apply all migrations (see bootstrap.sh for the sequence)
```

### Option 2: Nuclear reset (containers + volumes)

**DANGER: DB volume, Grafana volume, and all containers removed.**

```bash
cd platform
docker compose down -v   # -v removes named volumes (openfdd_db, grafana_data)
docker compose up -d --build
# Then re-run migrations as in bootstrap.sh
```

### Option 3: Delete via API

Use CRUD deletes to remove specific sites, equipment, or points. Data cascades as described above.

---

## Unit tests

- **`tools/test_crud_api.py`** — End-to-end: creates then deletes site, equipment, points. Deletes cascade (timeseries, fault_results for site). Run against live API.
- **`open_fdd/tests/platform/test_crud_api.py`** — Unit tests with mocked DB; verify API contract and status codes.
