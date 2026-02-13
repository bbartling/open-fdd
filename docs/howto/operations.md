---
title: Operations
parent: How-to Guides
nav_order: 2
---

# Operations

---

## Start / stop / restart

```bash
cd platform
docker compose down
docker compose up -d
```

Reboot: containers stop unless Docker or systemd is configured to start them on boot.

---

## When to rebuild

| Change | Action |
|--------|--------|
| **Log limits, retention SQL, Grafana dashboards** | `docker compose up -d` (restart). Log limits and new dashboards apply after restart. |
| **Open-Meteo driver** (new weather points: solar, cloud, wind_dir) | Rebuild weather-scraper: `docker compose build weather-scraper && docker compose up -d weather-scraper` |
| **API, FDD loop, BACnet scraper code** | `docker compose up -d --build` (rebuild affected services) |
| **Grafana dashboards missing** | `./scripts/bootstrap.sh --reset-grafana` |

---

## Resource check

```bash
free -h && uptime && echo "---" && docker stats --no-stream 2>/dev/null
```

---

## Database

```bash
cd platform
docker compose exec db psql -U postgres -d openfdd -c "\dt"
```

---

## Unit tests

```bash
cd /home/ben/open-fdd
.venv/bin/python -m pytest open_fdd/tests/ -v
```
