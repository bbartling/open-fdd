---
title: Quick reference
parent: How-to Guides
nav_order: 0
nav_exclude: true
---

# Quick reference

One-page cheat sheet for Open-FDD. Details live in [Verification](verification), [Operations](operations), and [Configuration](../configuration).

---

## What it is

Open-F-DD is an open-source **analytics stack for smart buildings**: **site VOLTTRON** (ZMQ message bus) ingests BACnet/Modbus on the OT LAN and writes **SQL**; this repo provides **Postgres/Timescale**, optional **FastAPI + React** for Brick/SPARQL, and **FDD** rules. The app tier can run **on-prem or in the cloud** as long as it can reach the database securely.

---

## Endpoints and credentials

| Service | URL | Default credentials |
|---------|-----|---------------------|
| **DB (TimescaleDB)** | `127.0.0.1:5432/openfdd` (loopback) | postgres / postgres |
| **Grafana** | http://localhost:3000 | Optional (`--with-grafana`); admin / admin |
| **Frontend (React)** | http://localhost:5173 | Dashboard, Config, Points, Data model, Faults, Plots. Via Caddy: http://localhost:80. |
| **API (Swagger)** | http://localhost:8000/docs | REST API; Bearer auth when `OFDD_API_KEY` set. |
| **Optional Mosquitto** | localhost:1883 | **Optional** compose profile — generic MQTT; **not** the VOLTTRON bus ([MQTT integration](mqtt_integration)). |
| **VOLTTRON / Central** | (your deployment) | Built per **volttron-docker** README — BACnet/Modbus **only here**. |

On another host, replace `localhost` with the server IP (e.g. `http://192.168.204.16:8000`). For bootstrap options run `./scripts/bootstrap.sh --help`.

**Check API liveness** (when FastAPI is running):

```bash
curl -s http://localhost:8000/health
```

---

## Bootstrap output (after `./scripts/bootstrap.sh`)

```
DB:        127.0.0.1:5432/openfdd  (postgres/postgres; loopback bind)
Frontend:  http://localhost:5173   (npm run dev; optional Caddy)
API:       http://localhost:8000   (uvicorn; docs: /docs)
Grafana:   http://localhost:3000   (optional compose profile)
MQTT:      localhost:1883          (optional Mosquitto profile — not VOLTTRON ZMQ)
VOLTTRON:  (per volttron-docker / site LAN)
```

---

## Docker

| Action | Command |
|--------|--------|
| **Stop** | `cd stack && docker compose down` (or `docker compose -f stack/docker-compose.yml down` from repo root) |
| **Start / restart** | `cd stack && docker compose up -d` |
| **Reboot note** | Containers do not start automatically on host reboot unless Docker or systemd is configured to start them. |

From repo root, run compose from `stack/` or use `-f stack/docker-compose.yml`.

---

## Unit tests and formatter

```bash
# From repo root (install once: pip install -e ".[dev]")
cd /path/to/open-fdd
.venv/bin/python -m pytest open_fdd/tests/ -v
.venv/bin/python -m black .
```

See [Contributing](../contributing) for styleguides.

---

## Resource check

```bash
free -h && uptime && echo "---" && docker stats --no-stream 2>/dev/null
```

---

## Database (list tables)

```bash
cd stack
docker compose exec db psql -U postgres -d openfdd -c "\dt"
```

---

## Data flow check

```bash
cd stack
curl -s http://localhost:8000/points | head -c 500
curl -s http://localhost:8000/data-model/export | head -c 600

docker compose exec db psql -U postgres -d openfdd -c "SELECT id, name FROM sites ORDER BY name;"
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, site_id, name FROM equipment ORDER BY name LIMIT 20;"
docker compose exec db psql -U postgres -d openfdd -c "SELECT id, site_id, equipment_id, external_id FROM points ORDER BY external_id LIMIT 20;"
docker compose exec db psql -U postgres -d openfdd -c "SELECT ts, point_id, value FROM timeseries_readings ORDER BY ts DESC LIMIT 5;"
```

**Verify BACnet scraping:** `curl -s http://localhost:8000/timeseries/latest` (recent `ts` = data flowing). Scraper logs: `docker logs openfdd_bacnet_scraper --tail 30`. Full steps: [Verification — BACnet scraper](verification#validating-scrapers-and-fdd).

---

## Logs

All containers (last 50 lines):

```bash
docker compose -f stack/docker-compose.yml logs --tail 50
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
docker compose -f stack/docker-compose.yml logs -f --tail 20
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

## Docs PDF

Build a single PDF of the documentation (offline use or to commit to the repo):

```bash
python3 scripts/build_docs_pdf.py
# Output: pdf/open-fdd-docs.pdf. Requires pandoc and weasyprint (pip install weasyprint) or LaTeX.
```

---

For full procedures (migrations, run FDD now, danger zone, etc.) see [Operations](operations) and [Verification](verification).
