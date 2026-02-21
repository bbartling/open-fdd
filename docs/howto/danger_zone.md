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

**Full reset script:** `python tools/delete_all_sites_and_reset.py` uses only the API (GET /sites, DELETE /sites/{id} for each, then POST /data-model/reset). It does not run SQL inside containers—the same flow a future UI would use.

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

### Reset everything for testing

To get a clean slate and run tests (e.g. `graph_and_crud_test.py`) or re-import BACnet:

1. **Wipe sites and data model** (choose one):
   - **Bootstrap:** `./scripts/bootstrap.sh --reset-data` — Brings up the stack (if needed), runs migrations, then deletes all sites via the API and calls POST /data-model/reset. Use `OFDD_API_URL=http://192.168.204.16:8000` if the API is on another host.
   - **Standalone:** `python tools/delete_all_sites_and_reset.py` — Same effect (GET /sites, DELETE each, POST /data-model/reset). Use `BASE_URL=http://192.168.204.16:8000` if your API is on another host.  
   Both use only the API (no SQL or Docker exec). The TTL and graph end up empty.

2. **Faster FDD/scrapers for testing (optional):**  
   - **FDD:** Set `rule_interval_hours: 0.1` (6 min) or `1` in your config, or env `OFDD_RULE_INTERVAL_HOURS=0.1`. Fractional hours are supported; minimum sleep is 60 s.  
   - **BACnet:** Set `bacnet_scrape_interval_min: 1` (or env `OFDD_BACNET_SCRAPE_INTERVAL_MIN=1`) so the scraper runs every minute.  
   **Docker:** The compose file defaults to 5 min. To use 1 min, set `OFDD_BACNET_SCRAPE_INTERVAL_MIN=1` in **platform/.env**, then from the repo root run `cd platform && docker compose up -d` (or `./scripts/bootstrap.sh`) so the bacnet-scraper container gets the new env.  
   Restart the affected containers after changing (e.g. `docker restart openfdd_fdd_loop openfdd_bacnet_scraper`), or use **POST /run-fdd** / trigger file to run FDD immediately without changing the interval.

**Workflow: reset → test → Grafana**

To get a clean slate, create test data (BensOffice + BACnet points), then confirm in Grafana that scrapers and FDD are working:

1. **Reset:** `./scripts/bootstrap.sh --reset-data`  
   Brings up the stack, runs migrations, then wipes all sites and resets the data model. You do **not** need to run `delete_all_sites_and_reset.py` after this — it does the same thing.

2. **Create test data:** `python tools/graph_and_crud_test.py`  
   Creates the BensOffice site, equipment (BensFakeAhu, BensFakeVavBox), discovers BACnet points, and imports them. Leaves BensOffice in place so scrapers have points to scrape.  
   **Wait for scrapes before exit:** `python tools/graph_and_crud_test.py --wait-scrapes 2 --scrape-interval-min 1` (use `--scrape-interval-min` to match your scraper; Docker default is 5 unless you set `OFDD_BACNET_SCRAPE_INTERVAL_MIN` in platform/.env).

3. **Check Grafana:**  
   Wait for the next scraper runs (or use fast intervals as above). Then open:
   - **BACnet Timeseries** — scraper status (OK/Stale), last data time, and the **point** dropdown to plot a series.
   - **Weather (Open-Meteo)** — weather status and last data (if the test site has lat/lon or weather was configured).
   - **Fault Results (open-fdd)** — Fault Runner Status and Last ran (after at least one FDD run).

See [Verification & Data Flow](verification) for API checks and scraper validation.

---

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
