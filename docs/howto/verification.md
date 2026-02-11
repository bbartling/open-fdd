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
```

Follow:

```bash
docker compose -f platform/docker-compose.yml logs -f --tail 20
```

---

## Weather scraper

```bash
docker logs openfdd_weather_scraper --tail 30
curl -s 'http://localhost:8000/points' | grep -E 'temp_f|rh_pct'
docker exec openfdd_timescale psql -U postgres -d openfdd -t -c "SELECT COUNT(*) FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id WHERE p.external_id = 'temp_f';"
```

---

## FDD loop (rule runner)

```bash
docker logs openfdd_fdd_loop --tail 50
```
