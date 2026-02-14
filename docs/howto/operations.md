---
title: Operations
parent: How-to Guides
nav_order: 2
---

# Operations

---

## Bootstrap does not purge data

`./scripts/bootstrap.sh` does **not** wipe the database. It starts containers and runs migrations (idempotent). Only `--reset-grafana` wipes Grafana's volume. See [Danger zone](danger_zone) for when data is purged.

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
| **API code** (download, data-model, main) | `docker compose build api && docker compose up -d api` |
| **FDD loop, BACnet scraper code** | `docker compose build bacnet-scraper fdd-loop` (or `--build`); fdd-loop also mounts `open_fdd` from host, so host code changes apply on restart. |
| **Grafana dashboards missing** | `./scripts/bootstrap.sh --reset-grafana` |

---

## New SQL migrations

When upgrading to a release that adds migrations (e.g. `008_fdd_run_log.sql`, `009_analytics_motor_runtime.sql`):

```bash
cd platform
docker compose exec -T db psql -U postgres -d openfdd -f - < sql/008_fdd_run_log.sql
docker compose exec -T db psql -U postgres -d openfdd -f - < sql/009_analytics_motor_runtime.sql
```

Or re-run `./scripts/bootstrap.sh` (idempotent; safe for existing DBs).

---

## Run FDD rules now

**What “run now” means:** Run the fault rules immediately and (if using the loop) reset the countdown to the next scheduled run.

### How the schedule works

| Trigger file `config/.run_fdd_now` | Behavior |
|------------------------------------|----------|
| **Absent** (or deleted after use)   | Loop runs every **config duration** (`rule_interval_hours`, e.g. 3 h). Each run loads **`lookback_days`** of data (e.g. 3 days) and executes all rules. |
| **Present**                        | Loop detects it within **60 seconds**, runs FDD immediately, **deletes the file**, and resets the timer. Then back to the normal interval. |

So: no trigger file → runs on the configured interval with configured lookback. Create the file (or call `POST /run-fdd`) when you want one run now and then resume the normal schedule.

### Option A: Trigger the running loop (recommended when fdd-loop is in Docker)

The fdd-loop container runs on a schedule (e.g. every 3 hours). While it’s sleeping, it checks every **60 seconds** for the file `config/.run_fdd_now`. If that file exists, it runs FDD right away, deletes the file, and resets the timer. So creating that file = “run now and reset timer.”

**From host (config is mounted into the container):**
```bash
touch config/.run_fdd_now
# or
python tools/trigger_fdd_run.py
```

**From Swagger:** `POST /run-fdd` (API touches the same file in its config volume.)

**Watch it happen:** `docker logs -f openfdd_fdd_loop` — within ~60 s you should see “Trigger file detected → running now, timer reset” and then “FDD run OK: …”.

### Option B: One-shot run (no loop, no trigger file)

Run the rules once and exit. Use this when the loop isn’t running or you’re testing.

**On host:**
```bash
python tools/run_rule_loop.py
```

**Inside Docker:**
```bash
cd platform
docker compose exec fdd-loop python tools/run_rule_loop.py
```

**Summary:** For “update faults now” with the normal Docker loop, use **touch** (or the script or `POST /run-fdd`). For a single run without the loop, use the **Py script** (or the exec command above).

---

## Throttling and rate limiting

1. **No API rate limiting by default** — The API does not throttle incoming requests. Clients can call as often as they like unless you add rate limiting elsewhere.
2. **OT/building network is paced** — Outbound traffic to the building is throttled by configuration: BACnet scraper polls on an interval (e.g. every 5 minutes), the FDD loop runs on a schedule (e.g. every 3 hours), and the weather scraper runs on an interval (e.g. daily). We do not continuously hammer the BACnet or OT network; you can tune these intervals in platform config.
3. **Adding incoming rate limiting** — To limit how often external clients can call the API (e.g. for a busy integration or to protect the OT network), add rate limiting at the reverse proxy (e.g. Caddy with a rate-limit module) or with middleware. See [Security — Throttling and rate limiting](security#throttling-and-rate-limiting).

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

## Unit tests and formatter

```bash
# From repo root
.venv/bin/python -m pytest open_fdd/tests/ -v
.venv/bin/python -m black .
```

See [Quick reference](howto/quick_reference) for a one-page cheat sheet.
