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

When you delete via the API (Swagger, CRUD UI, or scripts):

| Delete | Cascades to |
|--------|-------------|
| **Site** | Equipment, points, **timeseries_readings**, fault_results, fault_events, ingest_jobs |
| **Equipment** | Points (with that equipment_id), **timeseries_readings** for those points |
| **Point** | **timeseries_readings** for that point |

So deleting a site removes all its points and **all their timeseries data from the database**. The DB uses `ON DELETE CASCADE`: site → equipment & points → timeseries_readings. So when the data model reference is removed (site/equipment/point), the corresponding timeseries rows are **physically deleted**—no SQL or container access needed. There are no orphan rows left that a user could not see or clean up via the CRUD (or a future React UI). `DELETE /sites/{id}`, `DELETE /equipment/{id}`, and `DELETE /points/{id}` are **permanent**. A future front end can add confirmation prompts (e.g. “This will permanently delete all timeseries for this site. Continue?”) before calling these endpoints. After each delete, the **Brick TTL** (`config/brick_model.ttl`) is regenerated and written to disk. See [Data modeling](modeling/overview).

---

## Data retention policy

Bootstrap applies TimescaleDB retention (default **365 days**): chunks older than the configured interval are dropped from `timeseries_readings`, `fault_results`, `host_metrics`, `container_metrics`. This is automatic; no manual action.

To set retention: run bootstrap with `--retention-days N` or set `OFDD_RETENTION_DAYS` in `platform/.env` before bootstrap. See [Configuration — Edge / resource limits](configuration#edge--resource-limits).

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

### Option 3: Empty data model via API (sites + reset)

To clear the **data model** (Brick TTL and in-memory graph) but keep the stack and DB schema:

1. **Delete every site** via the API (e.g. `python tools/delete_all_sites_and_reset.py`, or `GET /sites` then `DELETE /sites/{id}` for each). Cascade removes equipment, points, and timeseries.
2. **POST /data-model/reset** — Clears the in-memory graph and repopulates from the DB only (Brick). BACnet triples and orphans are removed; the graph now has only what’s in the DB. Since the DB has no sites, the TTL is effectively empty and is written to `config/brick_model.ttl`.

**Important:** `GET /data-model/ttl` (and `?save=true`) always reflects the **current DB**: it syncs Brick from the DB, then serializes the graph. So if you still see sites/points in the TTL after “delete all sites + reset”, you are either (1) calling a **different** API host (e.g. script used `localhost:8000` but you curl `192.168.204.16:8000`), or (2) another process (e.g. weather scraper) re-created a site/points before you fetched the TTL. Use the same `BASE_URL` for the script and for curl, and run `GET /sites` after the script to confirm the list is empty.

### Option 4: Delete via API (specific entities)

Use CRUD deletes to remove specific sites, equipment, or points. Data cascades as described above.

---

## Unit tests

- **`tools/test_crud_api.py`** — End-to-end: creates then deletes site, equipment, points. Deletes cascade (timeseries, fault_results for site). Run against live API.
- **`open_fdd/tests/platform/test_crud_api.py`** — Unit tests with mocked DB; verify API contract and status codes.
