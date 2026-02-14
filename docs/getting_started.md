---
title: Getting Started
nav_order: 3
---

# Getting Started

Get the Open-FDD platform running in minutes.

---

## Prerequisites

- Docker and Docker Compose (or `docker-compose`)
- Optional: diy-bacnet-server as sibling repo (for BACnet ingestion)

---

## 1. Clone and bootstrap

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

This builds and starts the full stack: TimescaleDB, Grafana, API, BACnet scraper, weather scraper, FDD loop. Waits for Postgres (~15s), then prints URLs.

---

## 2. Verify

```bash
./scripts/bootstrap.sh --verify
```

Lists containers and tests DB reachability.

**Bootstrap options:** `--verify` (check status), `--minimal` (DB + Grafana only), `--reset-grafana` (wipe Grafana volume, re-apply provisioning).

---

## 3. Access services

| Service | URL |
|---------|-----|
| Grafana | http://localhost:3000 |
| API (Swagger) | http://localhost:8000/docs |
| BACnet Swagger | http://localhost:8080/docs |

Default Grafana login: admin / admin.

**Grafana provisioning:** TimescaleDB datasource and Open-FDD dashboards are provisioned from config. No manual setup needed. Dashboards appear under **Open-FDD**: BACnet Timeseries, **Fault Results** (fault runner status, last run time, weather faults, fault flags by fault_id), System Resources (host + container metrics), **Weather (Open-Meteo)** (temp, solar, wind, cloud). If dashboards show "no datasource" or wrong DB, run:

```bash
./scripts/bootstrap.sh --reset-grafana
```

This wipes Grafana's volume and re-applies provisioning. DB and other services are unchanged.

---

## 4. Minimal mode (DB + Grafana only)

On constrained hardware or when scraping externally:

```bash
./scripts/bootstrap.sh --minimal
```

---

## 5. First data flow check

```bash
curl -s http://localhost:8000/health && echo ""
curl -s http://localhost:8000/sites | head -c 300
curl -s http://localhost:8000/points | head -c 500
```

- `/health` → `{"status":"ok"}`
- `/sites` → JSON array (may be empty until scrapers create a site)
- `/points` → JSON array (populated after BACnet/weather scrapers run)

---

## 6. Unit tests

```bash
cd open-fdd
.venv/bin/python -m pytest open_fdd/tests/ -v
```

---

## Next steps

- [Verification](howto/verification) — Access logs, check data flow, Grafana dashboards
- [Configuration](configuration) — Log limits, data retention (~200 GB / 1 year)
- [BACnet setup](bacnet/overview) — Discover devices, configure scrape
- [Data modeling](modeling/overview) — Export points, map Brick types, validate
- [Rules](rules/overview) — Rule types and expression cookbook
- [Verification](howto/verification) — Logs, data flow checks
