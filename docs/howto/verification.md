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

Data retention is 1 year by default (TimescaleDB drops chunks older than 365 days). Keeps disk under ~200 GB for typical edge. To change: edit `platform/sql/007_retention.sql` (e.g. `'180 days'`, `'2 years'`). See [Configuration → Edge limits](configuration#edge--resource-limits).
