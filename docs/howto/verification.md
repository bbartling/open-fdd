---
title: Verification & Data Flow
parent: How-to Guides
nav_order: 1
---

# Verification and Data Flow

Checks to confirm the platform is running and data is flowing.

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

# DB checks (from platform dir)
cd platform
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
- **Grafana:** Open **Fault Results (open-fdd)**. The **Fault Runner Status** and **Fault Runner — Last ran** panels show status (OK/Error/Never) and a human-readable “last ran” time (e.g. “2 hours ago”).

**BACnet scraper:**

- **Grafana:** Open **BACnet Timeseries**. At the top, **BACnet scraper status** shows OK (green) if any BACnet point has received data in the last 15 minutes, otherwise Stale (yellow). **Last BACnet data** shows a human-readable timestamp (e.g. “3 min ago”). The **point** dropdown lists all BACnet points by raw object name (from discovery) so you can plot by name.
- **API:** `GET /points?site_id=<uuid>` and check which points have `bacnet_device_id` and `object_identifier`. Recent data appears in Grafana or in `timeseries_readings` (see Data flow check above if you do use DB access).

**Manual verification (BACnet scraping after graph_and_crud_test.py):**

1. **Grafana** — Open **BACnet Timeseries** (http://localhost:3000). Check **BACnet scraper status** (OK = data in last 15 min) and **Last BACnet data**. Pick a **point** from the dropdown and confirm the time series panel shows recent points.
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
   If this returns rows with recent `ts`, the scraper is writing and Grafana will show them.

**Note:** `graph_and_crud_test.py` now imports 2 BACnet points (SA-T, ZoneTemp) into **BensOffice** in step [4f2], so after the test BensOffice has points the scraper can poll. The test uses pre-tagged payloads (simulating the output of the **AI-assisted tagging** step). The full workflow with an LLM is: GET /data-model/export → tag with ChatGPT or another LLM (see [AI-assisted data modeling](../modeling/ai_assisted_tagging) and **AGENTS.md**) → PUT /data-model/import. The demo-import site created in [4g] is still deleted in [20c]; only BensOffice remains with BACnet points. Wait at least one scrape interval (see `OFDD_BACNET_SCRAPE_INTERVAL_MIN`, default 5 min) or restart the scraper, then check Grafana or the commands above.

**Weather (Open-Meteo):**

- **Grafana:** Open **Weather (Open-Meteo)**. At the top, **Weather data status** shows OK if any weather point has data in the last 25 hours, otherwise Stale. **Last weather data** shows a human-readable timestamp. Weather is typically fetched every 24 hours.
- **API / logs:** `GET /points` and filter for weather `external_id`s (e.g. `temp_f`, `rh_pct`). Or `docker logs openfdd_weather_scraper --tail 30` to see the last fetch.

---

## Logs

**Access:** All containers use log rotation (100 MB × 3 files per container). See [Configuration → Edge limits](configuration#edge--resource-limits).

All containers (last 50 lines):

```bash
docker compose -f platform/docker-compose.yml logs --tail 50
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
docker compose -f platform/docker-compose.yml logs -f --tail 20
```

---

## Weather scraper

```bash
docker logs openfdd_weather_scraper --tail 30
curl -s 'http://localhost:8000/points' | grep -E 'temp_f|rh_pct|shortwave_wm2|cloud_pct'
docker exec openfdd_timescale psql -U postgres -d openfdd -t -c "SELECT COUNT(*) FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id WHERE p.external_id = 'temp_f';"
```

---

## Grafana (provisioning)

Provisioning files live in `platform/grafana/`:

| Path | Purpose |
|------|---------|
| `provisioning/datasources/datasource.yml` | TimescaleDB datasource (uid: openfdd_timescale, default DB: openfdd) |
| `provisioning/dashboards/dashboards.yml` | Loads JSON from `/var/lib/grafana/dashboards` |
| `dashboards/*.json` | BACnet Timeseries, Fault Results, System Resources (host + Docker), **Weather (Open-Meteo)** |

**Dashboards:**
- **BACnet Timeseries** — BAS point values by site/device
- **Fault Results** — FDD fault flags over time
- **System Resources** — Host memory, load, container CPU/memory
- **Weather (Open-Meteo)** — Temp, humidity, dew point, wind, solar/radiation, cloud cover (select site in dropdown)

Verify provisioning is mounted:

```bash
docker exec openfdd_grafana ls -la /etc/grafana/provisioning/datasources/
docker exec openfdd_grafana ls -la /var/lib/grafana/dashboards/
```

If datasource or dashboards are wrong after a previous Grafana run:

```bash
./scripts/bootstrap.sh --reset-grafana
```

---

## FDD loop (rule runner)

```bash
docker logs openfdd_fdd_loop --tail 50
```

---

## Database retention

Data retention is set at bootstrap (default 365 days). TimescaleDB drops chunks older than the configured interval. To change: use `--retention-days N` when running bootstrap or set `OFDD_RETENTION_DAYS` in `platform/.env`. See [Configuration — Edge / resource limits](configuration#edge--resource-limits).
