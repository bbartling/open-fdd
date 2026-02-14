---
title: Quick reference
parent: How-to Guides
nav_order: 0
---

# Quick reference

One-page cheat sheet for Open-FDD. Details live in [Verification](howto/verification), [Operations](howto/operations), and [Configuration](configuration).

---

## What it is

Open-FDD is an open-source **edge analytics platform for smart buildings** that ingests BACnet and other OT telemetry, stores it in TimescaleDB, and runs rule-based fault detection and diagnostics locally with Grafana dashboards and APIs. As the open alternative to proprietary tools like SkyFoundry’s SkySpark, it gives operators full control, lower cost, and cloud-agnostic deployment, and already powers real-world HVAC optimization and commissioning workflows.

---

## Endpoints and credentials

| Service | URL | Default credentials |
|---------|-----|---------------------|
| **DB (TimescaleDB)** | `localhost:5432/openfdd` | postgres / postgres |
| **Grafana** | http://localhost:3000 | admin / admin |
| **API (Swagger)** | http://localhost:8000/docs | — |
| **BACnet Swagger** | http://localhost:8080/docs | diy-bacnet-server |

On another host, replace `localhost` with the server IP (e.g. `http://192.168.204.16:8000`).

---

## Bootstrap output (after `./scripts/bootstrap.sh`)

```
DB:       localhost:5432/openfdd  (postgres/postgres)
Grafana:  http://localhost:3000   (admin/admin)
API:      http://localhost:8000   (docs: /docs)
BACnet:   http://localhost:8080   (diy-bacnet-server Swagger)
```

---

## Docker

| Action | Command |
|--------|--------|
| **Stop** | `docker compose -f platform/docker-compose.yml down` |
| **Start / restart** | `docker compose -f platform/docker-compose.yml up -d` |
| **Reboot note** | Containers do not start automatically on host reboot unless Docker or systemd is configured to start them. |

From repo root, run compose from `platform/` or use `-f platform/docker-compose.yml`.

---

## Unit tests and formatter

```bash
# From repo root
cd /path/to/open-fdd
.venv/bin/python -m pytest open_fdd/tests/ -v
.venv/bin/python -m black .
```

See [CONTRIBUTING.md](https://github.com/bbartling/open-fdd/blob/master/CONTRIBUTING.md) for styleguides.

---

## Resource check

```bash
free -h && uptime && echo "---" && docker stats --no-stream 2>/dev/null
```

---

## Database (list tables)

```bash
cd platform
docker compose exec db psql -U postgres -d openfdd -c "\dt"
```

---

## Data flow check

```bash
cd platform
curl -s http://localhost:8000/points | head -c 500
curl -s http://localhost:8000/data-model/export | head -c 600

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

Per container (last 30 lines):

```bash
docker logs openfdd_api --tail 30
docker logs openfdd_bacnet_scraper --tail 30
docker logs openfdd_weather_scraper --tail 30
docker logs openfdd_fdd_loop --tail 30
docker logs openfdd_bacnet_server --tail 30
docker logs openfdd_grafana --tail 30
docker logs openfdd_timescale --tail 30
```

Follow live:

```bash
docker compose -f platform/docker-compose.yml logs -f --tail 20
```

---

## Weather scraper (runner)

```bash
docker logs openfdd_weather_scraper --tail 30
curl -s 'http://localhost:8000/points' | grep -E 'temp_f|rh_pct'
docker exec openfdd_timescale psql -U postgres -d openfdd -t -c "SELECT COUNT(*) FROM timeseries_readings tr JOIN points p ON p.id = tr.point_id WHERE p.external_id = 'temp_f';"
```

---

## FDD rule runner

```bash
docker logs openfdd_fdd_loop --tail 50
```

---

For full procedures (migrations, run FDD now, danger zone, etc.) see [Operations](howto/operations) and [Verification](howto/verification).
