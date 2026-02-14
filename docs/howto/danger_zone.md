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

`DELETE /sites/{id}`, `DELETE /equipment/{id}`, and `DELETE /points/{id}` remove the entity and all dependent data. This is **permanent**. After each delete (and after every create/update on sites, equipment, or points), the **Brick TTL** (`config/brick_model.ttl`) is **regenerated from the current DB** and written to disk, so the Brick data model stays in sync with CRUD and timeseries. See [System Modeling](modeling/overview).

---

## Data retention policy

`007_retention.sql` adds TimescaleDB retention: chunks older than **1 year** are dropped from `timeseries_readings`, `fault_results`, `host_metrics`, `container_metrics`. This is automatic; no manual action.

To change retention: edit the `INTERVAL` in `platform/sql/007_retention.sql` and re-apply (or adjust via TimescaleDB functions).

---

## How to purge (intentional wipe)

### Start completely from scratch (recommended)

**DANGER: All data is lost — database, Grafana, and all container state.**

To blast away the project and start over with a clean DB and Grafana:

```bash
cd open-fdd/platform
docker compose down -v
cd ..
./scripts/bootstrap.sh
```

- **`down -v`** removes containers and **named volumes** (`openfdd_db`, `grafana_data`). All timeseries, fault results, sites, points, and Grafana dashboards are gone.
- **`bootstrap.sh`** brings the stack back up, creates a fresh DB (init scripts run automatically), applies migrations, and leaves you with an empty project ready to reconfigure.

---

### Option 1: Drop and recreate the database only

**DANGER: All DB data is lost.** Grafana volume is unchanged.

```bash
cd platform
docker compose exec db psql -U postgres -c "DROP DATABASE openfdd;"
docker compose exec db psql -U postgres -c "CREATE DATABASE openfdd;"
# From repo root, re-run bootstrap to apply migrations:
# ./scripts/bootstrap.sh
```

### Option 2: Nuclear reset (containers + volumes, manual)

**DANGER: DB volume, Grafana volume, and all containers removed.**

Same effect as “Start completely from scratch” but without calling bootstrap:

```bash
cd platform
docker compose down -v
docker compose up -d --build
# Then from repo root: ./scripts/bootstrap.sh (waits for Postgres, applies migrations)
```

### Option 3: Delete via API

Use CRUD deletes to remove specific sites, equipment, or points. Data cascades as described above.

---

## Unit tests

- **`tools/test_crud_api.py`** — End-to-end: creates then deletes site, equipment, points. Deletes cascade (timeseries, fault_results for site). Run against live API.
- **`open_fdd/tests/platform/test_crud_api.py`** — Unit tests with mocked DB; verify API contract and status codes.
