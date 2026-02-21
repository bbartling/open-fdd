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
- **Grafana:** Use the provisioned datasource (`openfdd_timescale`) in **Explore** or build a dashboard with the [Grafana SQL cookbook](grafana_cookbook) (Recipe 2).

**BACnet scraper:**

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

**Note:** `graph_and_crud_test.py` now imports 2 BACnet points (SA-T, ZoneTemp) into **BensOffice** in step [4f2], so after the test BensOffice has points the scraper can poll. The test uses pre-tagged payloads (simulating the output of the **AI-assisted tagging** step). The full workflow with an LLM is: GET /data-model/export → tag with ChatGPT or another LLM (see [AI-assisted data modeling](../modeling/ai_assisted_tagging) and **AGENTS.md**) → PUT /data-model/import. The demo-import site created in [4g] is still deleted in [20c]; only BensOffice remains with BACnet points. Wait at least one scrape interval (see `OFDD_BACNET_SCRAPE_INTERVAL_MIN`, default 5 min) or restart the scraper, then check Grafana or the commands above.

**Weather (Open-Meteo):**

- **Grafana:** Use Recipe 4 in the [Grafana SQL cookbook](grafana_cookbook) to build a Weather dashboard (status, last data, temp/humidity series).
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

## Grafana (datasource only)

Only the **TimescaleDB datasource** is provisioned (`platform/grafana/provisioning/datasources/datasource.yml`, uid: `openfdd_timescale`, database: `openfdd`). No dashboards are provisioned. Build your own using the [Grafana SQL cookbook](grafana_cookbook).

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

Data retention is set at bootstrap (default 365 days). TimescaleDB drops chunks older than the configured interval. To change: use `--retention-days N` when running bootstrap or set `OFDD_RETENTION_DAYS` in `platform/.env`. See [Configuration — Edge / resource limits](configuration#edge--resource-limits).
