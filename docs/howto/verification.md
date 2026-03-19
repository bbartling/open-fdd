---
title: Verification & Data Flow
parent: How-to Guides
nav_order: 1
nav_exclude: true
---

# Verification and Data Flow

Checks to confirm the platform is running and data is flowing.

---

## Home page / frontend won't load

If **http://localhost** or **http://\<host-ip\>** (e.g. http://192.168.204.16) does not show the Open-FDD UI:

1. **Check that containers are running**
   ```bash
   cd stack
   docker compose ps
   ```
   Ensure `openfdd_frontend` and `openfdd_caddy` are **Up**. If `openfdd_frontend` is restarting or exited, see step 2.

2. **Frontend logs** (Vite must finish `npm install` then `npm run dev`; first start can take 1–2 minutes)
   ```bash
   docker compose -f stack/docker-compose.yml logs frontend --tail 80
   ```
   Look for `Local: http://localhost:5173/` or errors (e.g. EADDRINUSE, npm install failure). If the container keeps exiting, try a clean frontend install: `./scripts/bootstrap.sh --frontend` then `./scripts/bootstrap.sh`.

3. **Caddy logs** (proxy to frontend)
   ```bash
   docker compose -f stack/docker-compose.yml logs caddy --tail 30
   ```
   If you see 502 Bad Gateway, the frontend is not ready yet; wait for the frontend healthcheck to pass (Caddy starts only when frontend is healthy).

4. **Try the dev server directly** (bypass Caddy)
   - Open **http://localhost:5173** (or http://\<host-ip\>:5173). If that loads, the frontend is fine and the issue is Caddy or port 80 (e.g. another service binding to 80).

5. **Port 80 in use**
   - On Linux: `sudo ss -tlnp | grep :80` or `sudo lsof -i :80`. Stop the conflicting service or change Caddy’s host port in `stack/docker-compose.yml` (e.g. `"8080:80"`).

6. **Remote access**
   - From another machine use **http://\<server-ip\>** (port 80) or **http://\<server-ip\>:5173**. Ensure firewall allows 80 and 5173.

---

## Health

```bash
curl -s http://localhost:8000/health && echo ""
```

---

## Data flow check

```bash
curl -s http://localhost:8000/points | head -c 500
curl -s http://localhost:8000/data-model/export | head -c 600

# DB checks (from stack dir)
cd stack
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, name FROM sites ORDER BY name;"
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, site_id, name FROM equipment ORDER BY name LIMIT 20;"
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, site_id, equipment_id, external_id FROM points ORDER BY external_id LIMIT 20;"
docker compose exec db psql -U postgres -d openfdd -c "SELECT ts, point_id, value FROM timeseries_readings ORDER BY ts DESC LIMIT 5;"
```

---

## Validating scrapers and FDD (API + Grafana)

You can confirm that the BACnet scraper, weather scraper, and FDD loop are running and writing data **without running SQL inside containers**.

**FDD (fault detection):**

- **API:** `curl -s http://localhost:8000/run-fdd/status` returns the last run time and status (`ok` / `error`). If the FDD loop has run at least once, you will see `run_ts` and `status`.
- **Grafana:** Use the provisioned datasource (`openfdd_timescale`) in **Explore** or build a dashboard with the [Grafana SQL cookbook](grafana_cookbook) (Recipe 2).

**BACnet scraper:**

**Quick verification (is BACnet scraping?):**

1. **Scraper running and logging:**  
   `docker logs openfdd_bacnet_scraper --tail 30`  
   Look for "Scraped N points" or similar; no repeated connection/401 errors.

2. **API — latest readings (BACnet + weather):**  
   `curl -s "http://localhost:8000/timeseries/latest"`  
   If scraping is working, you get at least one object with `point_id`, `value`, and a recent `ts` (e.g. within the last scrape interval). With auth: `curl -s -H "Authorization: Bearer YOUR_KEY" "http://localhost:8000/timeseries/latest"`.

3. **DB — recent BACnet-only rows:**  
   `docker exec openfdd_timescale psql -U postgres -d openfdd -t -c "SELECT ts, p.external_id, tr.value FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id WHERE p.bacnet_device_id IS NOT NULL ORDER BY tr.ts DESC LIMIT 10;"`  
   Recent `ts` and rows = scraper is writing. Empty or stale `ts` (older than the expected scrape interval) = no BACnet points in the data model, or scraper not reaching the gateway.

**Prerequisites for BACnet data:** Points in the data model must have `bacnet_device_id`, `object_identifier`, and `polling = true` (or equivalent). Add them via BACnet discovery → Add to data model, or data-model import. If there are no such points, the scraper has nothing to poll.

- **Grafana:** Build a BACnet dashboard from the [Grafana SQL cookbook](grafana_cookbook) (Recipe 1), or run the same SQL in **Explore**.
- **API:** `GET /points?site_id=<uuid>` and check which points have `bacnet_device_id` and `object_identifier`. Recent data appears in `timeseries_readings` (see Data flow check above).

**Manual verification (BACnet scraping after graph_and_crud_test.py):**

1. **Grafana** — Open http://localhost:3000, go to **Explore**, choose the **openfdd_timescale** datasource, and run the BACnet scraper status or time series SQL from the [Grafana SQL cookbook](grafana_cookbook) (Recipe 1). Or build a full dashboard from the cookbook and confirm panels show recent data.
2. **API** — List BACnet points (replace `SITE_ID` with your BensOffice site UUID from `curl -s http://localhost:8000/sites`):
   ```bash
   curl -s "http://localhost:8000/points?site_id=SITE_ID" | python3 -c "
   import sys, json
   d = json.load(sys.stdin)
   points = d if isinstance(d, list) else []
   for p in points:
       if isinstance(p, dict) and p.get('bacnet_device_id'):
           print(p.get('external_id',''), p.get('object_identifier',''), p.get('polling'))
   "
   ```
   If you see output like `SA-T analog-input,2 True`, those points are in the DB and the scraper will poll them. If the API returns an error (e.g. invalid `SITE_ID`), you will see no output instead of a crash.
3. **Scraper logs** — `docker logs openfdd_bacnet_scraper --tail 40` — look for "Scraped N points" or polling/write lines without errors.
4. **DB (optional)** — Recent BACnet readings:
   ```bash
   docker exec openfdd_timescale psql -U postgres -d openfdd -t -c "SELECT ts, p.external_id, tr.value FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id WHERE p.bacnet_device_id IS NOT NULL ORDER BY tr.ts DESC LIMIT 10;"
   ```
   If this returns rows with recent `ts`, the scraper is writing; any dashboard you build from the cookbook will show them.

**Note:** `graph_and_crud_test.py` imports 2 BACnet points (SA-T, ZoneTemp) into **TestBenchSite** in step [4f1], so after the test TestBenchSite has points the scraper can poll. The test uses pre-tagged payloads (simulating the output of the **AI-assisted tagging** step). The full workflow with an LLM is: GET /data-model/export → tag with ChatGPT or another LLM (see [AI-assisted data modeling](../modeling/ai_assisted_tagging)) → PUT /data-model/import. The demo-import site created in [4g] is still deleted in [20c]; only TestBenchSite remains with BACnet points. Wait at least one scrape interval (see `OFDD_BACNET_SCRAPE_INTERVAL_MIN`, default 5 min) or restart the scraper, then check Grafana or the commands above.

**Weather (Open-Meteo):**

- **Grafana:** Use Recipe 4 in the [Grafana SQL cookbook](grafana_cookbook) to build a Weather dashboard (status, last data, temp/humidity series).
- **API / logs:** `GET /points` and filter for weather `external_id`s (e.g. `temp_f`, `rh_pct`). Or `docker logs openfdd_weather_scraper --tail 30` to see the last fetch.

**Plots — fault line (0/1 when condition is true):**

The fault overlay on Plots is driven by `GET /analytics/fault-timeseries`: one row per (time bucket, fault_id) where `fault_results` has data. The frontend shows **1** only in buckets where the fault fired, and **0** otherwise. If you see a **constant flat line** (usually flat at 1):

- **One long segment:** The API returns one time bucket per fault (e.g. one FDD run). With a **day** bucket and a 1-day range, that one bucket fills the chart → flat 1 all day. To see discrete 0/1 steps: use a **wider time range** (e.g. 7 days) so you get multiple buckets and see which days/hours had the fault, or use **hour** bucket (used automatically when range ≤ 2 days) so each hour is 0 or 1.
- **FDD run frequency:** Fault results are written when the FDD loop runs (e.g. every `rule_interval_hours`). To see the fault only when the condition is true, ensure the loop runs multiple times in your range and the rule actually evaluates to 0 sometimes; otherwise every bucket may show 1.
- **Check the API:** `curl -s "http://localhost:8000/analytics/fault-timeseries?site_id=YOUR_SITE&start_date=2026-03-01&end_date=2026-03-08&bucket=hour"` — you should see multiple `series` entries with different `time` values when the fault fires in different hours.

---

## Logs

**Access:** All containers use log rotation (100 MB × 3 files per container). See [Configuration → Edge limits](configuration#edge--resource-limits).

All containers (last 50 lines):

```bash
docker compose -f stack/docker-compose.yml logs --tail 50
```

Per container:

```bash
docker logs openfdd_api --tail 30
docker logs openfdd_bacnet_scraper --tail 30
docker logs openfdd_weather_scraper --tail 30
docker logs openfdd_fdd_loop --tail 30
docker logs openfdd_host_stats --tail 30
```

Follow logs live:

```bash
docker compose -f stack/docker-compose.yml logs -f --tail 20
```

---

## Weather scraper

```bash
docker logs openfdd_weather_scraper --tail 30
curl -s 'http://localhost:8000/points' | grep -E 'temp_f|rh_pct|shortwave_wm2|cloud_pct'
docker exec openfdd_timescale psql -U postgres -d openfdd -t -c "SELECT COUNT(*) FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id WHERE p.external_id = 'temp_f';"
```

---

## Weather page: "No weather points for this site"

The Weather UI shows points (`temp_f`, `rh_pct`, `wind_mph`, etc.) only after **Open-Meteo data has been fetched and stored for the selected site**. Two ways that can happen:

1. **Standalone weather-scraper** (`openfdd_weather_scraper`)  
   Runs on an interval (default **24 hours**). After stack start it does a first fetch soon; then it sleeps until the next interval. If you just brought the stack up, wait for that first run or trigger once (see below).

2. **FDD loop** (`openfdd_fdd_loop`)  
   When Open-Meteo is enabled, **weather is fetched at the start of each FDD run** (every `rule_interval_hours`). So the next time the AFDD routine runs, it will fetch weather (1-day lookback) and create/update weather points. No separate weather-scraper needed; do not run both to avoid redundant fetches.

**Checklist:**

- **Open-Meteo enabled:** Config → Open-Meteo (weather) → "Enable Open-Meteo" on, or `GET /config` has `open_meteo_enabled: true` (and in `config/data_model.ttl`: `ofdd:openMeteoEnabled true`).
- **Which runner is active:**
  - `docker logs openfdd_weather_scraper --tail 30` — look for "Open-Meteo fetch OK" and "Sleeping N h until next fetch".
  - `docker logs openfdd_fdd_loop --tail 50` — look for "Open-Meteo fetch OK before FDD run".
- **Site match:** Weather is stored for the site given by `open_meteo_site_id` (default `"default"`), which resolves to the **first site** in the DB if no site named "default" exists. Ensure the site you have selected in the UI is that site (e.g. TestBenchSite if it’s the only/first site).

**If the fetch ran recently but the Weather page still shows "No weather points for this site":** (1) Note which site is selected in the top bar (e.g. TestBenchSite). (2) In Config → Open-Meteo set **"Site for weather points"** to that exact site name and Save. (3) Run a one-off fetch below or wait for the next run. (4) On the Weather page, keep that site selected and refresh. To confirm points: `curl -s "http://localhost:8000/points?site_id=<SITE_UUID>" | grep -E "temp_f|rh_pct"` (use UUID from GET /sites or the frontend URL `?site=...`).

**Populate weather immediately (one-off fetch):**

From the repo (with stack up and DB/API reachable):

```bash
# Uses GET /config or env (OFDD_OPEN_METEO_*, OFDD_DB_DSN); writes to site from open_meteo_site_id
python -m open_fdd.platform.drivers.run_weather_fetch
```

Or from inside the API/worker image (replace with your image name if different):

```bash
docker compose -f stack/docker-compose.yml run --rm api python -m open_fdd.platform.drivers.run_weather_fetch
```

After a successful run, refresh the Weather page with the correct site selected; you should see temp/RH/wind panels.

---

## Grafana (datasource only)

Only the **TimescaleDB datasource** is provisioned (`stack/grafana/provisioning/datasources/datasource.yml`, uid: `openfdd_timescale`, database: `openfdd`). No dashboards are provisioned. Build your own using the [Grafana SQL cookbook](grafana_cookbook).

Verify the datasource is mounted:

```bash
docker exec openfdd_grafana ls -la /etc/grafana/provisioning/datasources/
```

To re-apply provisioning (e.g. after a bad upgrade): `./scripts/bootstrap.sh --reset-grafana`. This wipes the Grafana volume and re-provisions the datasource; DB data is unchanged.

---

## FDD loop (rule runner)

```bash
docker logs openfdd_fdd_loop --tail 50
```

---

## Database retention

Data retention is set at bootstrap (default 365 days). TimescaleDB drops chunks older than the configured interval. To change: use `--retention-days N` when running bootstrap or set `OFDD_RETENTION_DAYS` in `stack/.env`. See [Configuration — Edge / resource limits](configuration#edge--resource-limits).
