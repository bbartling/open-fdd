---
title: Grafana troubleshooting
parent: How-to Guides
nav_order: 40
---

# Grafana troubleshooting

This page covers common Open-FDD Grafana dashboard issues and how to fix them.

## Too many sites in dropdowns

**Symptom:** Weather, BACnet Timeseries, or other dashboards show many sites in the site dropdown (e.g. `demo-import-0b552001`, `demo-import-afa3f5bf`, …) along with your real site (e.g. `BensOffice`).

**Cause:** The database has multiple sites. Demo sites are created by tests or one-off imports; test runs now clean up their own demo site, but older runs may have left sites in the DB.

**Fix:**

1. **Remove unwanted sites via API** (keeps your real site and data):
   - List sites: `GET http://<api-host>:8000/sites`
   - Delete each demo site: `DELETE http://<api-host>:8000/sites/<site-uuid>`
   - Cascade deletes equipment, points, timeseries, and fault data for that site.

2. **Full reset** (only if you want to start from scratch):
   - Use `tools/delete_all_sites_and_reset.py` (set `BASE_URL` to your API, e.g. `http://192.168.204.16:8000`), then re-create your site and re-import BACnet/points as needed.

After cleanup, re-open the dashboard or refresh variables; the dropdown will show only the remaining sites.

---

## System Resources: “Container memory (MB)” / “Container CPU %” show No data

**Symptom:** Host stats (memory, load, swap) and the “Containers (latest)” table have data, but the time series panels “Container memory (MB)” and “Container CPU %” show **No data**.

**Cause:** Those panels use `$__timeFilter(ts)` so they only show points inside the dashboard time range. If the range doesn’t overlap your data (e.g. timezone mismatch or range too narrow), you get no series.

**Checks:**

1. **Confirm data exists**
   - In Grafana, open **Explore** → choose the Open-FDD TimescaleDB datasource and run:
   - `SELECT ts, container_name, mem_usage_bytes/1024/1024 AS mem_mb FROM container_metrics ORDER BY ts DESC LIMIT 20`
   - If this returns rows, data is present.

2. **Widen time range**
   - Set the dashboard time (top right) to **Last 24 hours** or **Last 6 hours** and refresh.

3. **Timezone**
   - Ensure the datasource or dashboard timezone matches where data is written (usually UTC). In **Data sources** → your PostgreSQL → **Settings**, check timezone options.

4. **Host-stats writing**
   - `docker logs openfdd_host_stats` should show periodic “Wrote host=ok containers=N”. If it never writes, fix the host-stats container (e.g. Docker socket mount, DB connection).

---

## Fault Results: “Fault Runner Status” or “Fault Runner — Last ran” show No data

**Symptom:** “Fault count (time range)” shows a number (e.g. 90) and you know FDD ran recently, but “Fault Runner Status” or “Fault Runner — Last ran” show **No data**.

**Cause:** Those panels read from `fdd_run_log`. If the panel query returns no row (or Grafana doesn’t treat the result as a single value), the stat shows “No data”.

**Checks:**

1. **Confirm `fdd_run_log` has rows**
   - In **Explore** or any SQL tool:  
     `SELECT run_ts, status, sites_processed, faults_written FROM fdd_run_log ORDER BY run_ts DESC LIMIT 5`
   - If this is empty, the FDD loop has never written a log entry (check `openfdd_fdd_loop` logs and DB connectivity).

2. **API**
   - `GET http://<api-host>:8000/run-fdd/status` should return the last run time and status. If that works but the panel doesn’t, the issue is the panel query or format.

3. **Dashboard fix**
   - The Status panel should return one row with a `value` column (and optionally a `time` column). If you still see “No data” after confirming rows exist, re-import the Fault Results dashboard from the repo; the panel query may have been updated to always return one row (e.g. with `COALESCE(..., 'never')` and a synthetic time).

---

## BACnet dashboard: all data and last scrape

The BACnet Timeseries dashboard is **graph-aligned**: it shows the same points as the SPARQL data model (`ofdd:polling true`). The DB is synced from the graph via the API (import/export, TTL). **All BACnet data** appears in the panels “All BACnet points (any site)”, “By device”, and “Single point”; the dropdowns list every point the scraper polls. **Last scrape** is represented by “BACnet scraper status” (OK if data in last 15 min) and “Last BACnet data” (timestamp of most recent reading). The “BACnet points (polling)” count should match the SPARQL count (e.g. from test step [25b]). If you see fewer points or stale status, see the sections below.

---

## BACnet Timeseries: only one point when TTL has many (TTL vs DB vs Grafana)

**Symptom:** `GET /data-model/ttl?save=true` shows many BACnet devices and objects (e.g. device 3456789, 3456790 with DAP-P, SA-T, ZoneTemp, VAVFlow, …), but the Grafana BACnet Timeseries dashboard only shows one site/device/point (e.g. demo-import-6bb347c8, 3456790, ZoneTemp).

**Cause: The scraper and Grafana use the database, not the TTL.** The TTL is built from: (1) **Brick from DB** — sites, equipment, and points in the `points` table; (2) **BACnet discovery** — device/object triples from `POST /bacnet/point_discovery_to_graph`. So the TTL can show many BACnet objects that were **discovered** but never **imported** into the DB. Only rows in the **`points`** table with `bacnet_device_id`, `object_identifier`, and `polling = true` are scraped and written to `timeseries_readings`. Grafana dropdowns query the DB, so they only list what exists in the DB.

**Fix: Import the BACnet points you want to scrape and see in Grafana.**

1. **Export** — `GET http://<api>:8000/data-model/export?bacnet_only=true` returns all discovered BACnet objects plus existing DB points. Rows with `point_id: null` are discovery-only (not yet in the DB).
2. **Tag** — For each row you want to scrape: set `site_id` (UUID from `GET /sites`), `external_id` (e.g. object name: ZoneTemp, SA-T, VAVFlow), and optionally `brick_type`, `rule_input`, `equipment_id`. Set **`polling: true`** so the scraper includes them.
3. **Import** — `PUT http://<api>:8000/data-model/import` with body `{ "points": [ ... ] }`. This creates or updates rows in `points`. The BACnet scraper (when `OFDD_BACNET_USE_DATA_MODEL=true`, default) loads points from the DB with `polling = true` and `bacnet_device_id` / `object_identifier` set, and writes to `timeseries_readings`. After the next scrape, Grafana will show the new series.

**Config:** The scraper reads from the **DB** (not the TTL). Set `OFDD_BACNET_USE_DATA_MODEL=true` (default) and `OFDD_BACNET_SERVER_URL` (e.g. `http://host.docker.internal:8080` in Docker). See `config/platform.example.yaml` and [Configuration](configuration).

---

## BACnet Timeseries: only one point or wrong site in dropdown

**Symptom:** BACnet Timeseries dashboard shows only one site/device/point in the dropdowns, or you expect more BACnet series.

**Cause:** The dropdowns are driven by the **DB** `points` table: sites with points that have `bacnet_device_id`, then devices and `external_id`s for that site. If only one point was imported (or only one has `polling = true`), the list will be short.

**Checks:**

1. **TTL vs DB** — If the TTL shows many BACnet objects but Grafana shows one, see [only one point when TTL has many](#bacnet-timeseries-only-one-point-when-ttl-has-many-ttl-vs-db-vs-grafana) above: import via export → tag → import.
2. **Use "All BACnet points (any site)"** — That panel lists every BACnet series with data in the time range. If only one series appears, only one point in the DB has been scraped recently.

3. **Confirm points in DB** — `GET /points?site_id=<uuid>`; check which have `bacnet_device_id`, `object_identifier`, `polling: true`. Ensure scraper is running (`docker logs openfdd_bacnet_scraper`) and `OFDD_BACNET_SERVER_URL` reaches diy-bacnet-server.
4. **Clean up sites** — See [Too many sites in dropdowns](#too-many-sites-in-dropdowns).

---

## BACnet: scraper “ran” but no data in panels

**Symptom:** Grafana shows “BACnet scraper ran a few minutes ago” (or status OK) but time series panels show “No data”.

**Causes and checks:**

1. **Scraper sees 0 points** — Log line “No BACnet points in data model” means the DB has no points with `bacnet_device_id`, `object_identifier`, and `polling = true`. Import points (e.g. run `python tools/graph_and_crud_test.py` which loads `tools/demo_site_llm_payload.json` into DemoSite and leaves it in place so dropdowns and scraper have many points).
2. **Scraper sees points but reads fail** — Logs show “Scrape cycle: 0 rows, N points, M errors”. Then the BACnet RPC to diy-bacnet-server is failing for some or all objects. Check:
   - `docker logs openfdd_bacnet_scraper --tail 80` for the actual error lines (e.g. “Line 1 analog-input,2: Error: …”).
   - `OFDD_BACNET_SERVER_URL` from the scraper container: it must reach diy-bacnet-server (e.g. `http://host.docker.internal:8080`; on Linux, `platform/docker-compose.yml` uses `extra_hosts: host.docker.internal:host-gateway`).
   - diy-bacnet-server has devices 3456789 and 3456790 (or whatever device IDs your points use) and exposes the object types in the payload (e.g. `analog-input`, `analog-output`). Objects like `network-port` may not have a readable present-value and can be skipped or show errors.
3. **Time range** — In Grafana, set the time range to “Last 15 minutes” or “Last 1 hour” so recent scrape data is included.
4. **Scraper shows only 2 points (2 devices)** — The DB may only have one site (e.g. BensOffice) with 2 BACnet points. Run `python tools/graph_and_crud_test.py` so DemoSite and all points from `tools/demo_site_llm_payload.json` are in the DB; step [25b] asserts SPARQL count = API/scraper count; Grafana dropdowns should match that count.
5. **“diy-bacnet-server unreachable: All connection attempts failed”** — The scraper cannot reach `OFDD_BACNET_SERVER_URL` (e.g. `http://host.docker.internal:8080`). Ensure the bacnet-server container is running (`docker ps`). On Linux, `platform/docker-compose.yml` sets `extra_hosts: host.docker.internal:host-gateway` for the scraper; if diy-bacnet runs on the host, ensure it listens on `0.0.0.0:8080` and that port 8080 is reachable.

---

## Quick reference

| Issue | What to check |
|-------|----------------|
| Too many sites | Delete demo sites via `DELETE /sites/{id}` or use `tools/delete_all_sites_and_reset.py`. |
| Container time series “No data” | Data in `container_metrics`? Widen time range; check timezone. |
| Fault Runner “No data” | Rows in `fdd_run_log`? `GET /run-fdd/status`; re-import dashboard if needed. |
| BACnet dropdown / one point | TTL has many but Grafana one? Import via GET /data-model/export → tag → PUT /data-model/import (see above). Confirm DB points and scraper. |
| Scraper only 2 points | Run `python tools/graph_and_crud_test.py` so DemoSite + many points exist; [25b] asserts SPARQL = API = scraper count. |
| diy-bacnet unreachable | Ensure bacnet-server container runs; check OFDD_BACNET_SERVER_URL and host.docker.internal (Linux: extra_hosts in docker-compose). |

All dashboards use the **Open-FDD TimescaleDB** PostgreSQL datasource (`openfdd_timescale`). Ensure it points at the same database as the API and scrapers (e.g. `openfdd_timescale` container).

To **add or build custom dashboards** (new panels, variables, SQL), see [Custom Grafana dashboards](grafana_custom_dashboards).
