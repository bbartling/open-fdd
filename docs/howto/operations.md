---
title: Operations
parent: How-to Guides
nav_order: 2
nav_exclude: true
---

# Operations

---

## Bootstrap does not purge data

`./scripts/bootstrap.sh` does **not** wipe the database. It starts containers and runs migrations (idempotent). Only `--reset-grafana` wipes Grafana's volume. See [Danger zone](danger_zone) for when data is purged.

---

## Start / stop / restart

From repo root:

```bash
cd stack
docker compose down
docker compose up -d
```

Or: `docker compose -f stack/docker-compose.yml up -d` from repo root. Reboot: containers stop unless Docker or systemd is configured to start them on boot.

---

## When to rebuild

| Change | Action |
|--------|--------|
| **Log limits, retention SQL, Grafana datasource** | `docker compose up -d` (restart). Log limits and datasource apply after restart. |
| **Open-Meteo / weather (legacy fork)** | If you still run a removed weather-scraper service, rebuild that image only. Default path: weather fetched with **FDD** or disabled. |
| **FastAPI code** (when you containerize it yourself) | Rebuild **your** `api` image or restart `uvicorn` on the host. |
| **VOLTTRON / historian** | Rebuild or restart **site** containers per **volttron-docker** / your fleet process — not covered by this repo’s slim compose. |
| **Legacy diy-bacnet + scraper fork** | Only if you restored removed services: see **`afdd_stack/legacy/README.md`**. Do **not** use for new BACnet ingest. |
| **All services (custom compose)** | `docker compose build && docker compose up -d` from **your** compose project. |
| **Grafana datasource missing or wrong** | `./scripts/bootstrap.sh --reset-grafana` |

---

## New SQL migrations

When upgrading to a release that adds migrations, apply any new files under `stack/sql/` in order, or re-run bootstrap:

```bash
cd stack
for f in $(printf '%s\n' sql/*.sql | sort); do
  [ -f "$f" ] && docker compose exec -T db psql -U postgres -d openfdd -f - < "$f" || true
done
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

### Verified: hot reload and config parity

- **Frontend (Config):** OpenFDD Config shows **Rule interval (hours)**, **Lookback (days)**, and **Rules dir** (e.g. `stack/rules`). These come from the knowledge graph (GET `/config`); edits are saved via PUT `/config`. **`rules_dir` is still required** — it is the path where rule YAML files are stored; both the FDD loop and the rules API use it.
- **Frontend (Faults):** The “FDD rule files (YAML)” section lists files in that rules dir (GET `/rules`). You can **upload** (paste YAML or choose file), **download**, and **delete** rule files, and click **Sync definitions** to update the fault_definitions table without waiting for the next FDD run. Fault definitions in the table come from the DB (synced from the YAML in `rules_dir` when rules run or when you sync). Timestamped **`test_*`** rule files with a long numeric suffix (e.g. `test_sensor_bounds_1774812747.yaml`) come from the **`4_hot_reload_test.py`** bench, not from bootstrap; the UI groups them as bench/E2E copies so you can delete them if they were left behind.
- **FDD loop (stack):** Each run (every `rule_interval_hours`) loads rules from `rules_dir` via `load_rules_from_dir(rules_path)` — no cache. So whether you edit files on disk or upload via the frontend, the next run uses the latest YAML. The loop uses `lookback_days` to pull that many days from the DB. In Docker the stack mounts `../stack/rules` at `/app/stack/rules` and sets `OFDD_RULES_DIR: "stack/rules"`.

**Tests:** `open_fdd/tests/platform/test_config.py` and `open_fdd/tests/platform/test_fdd_config_hot_reload.py` assert that GET /config exposes `rules_dir`, `rule_interval_hours`, `lookback_days`; that the FDD loop loads rules from the configured dir on every run (no cache); and that the rules API and the loop resolve the same path for a relative `rules_dir`. Run: `pytest open_fdd/tests/platform/test_config.py open_fdd/tests/platform/test_fdd_config_hot_reload.py -v`.

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

**Inside Docker** (one-shot, same code path as the long-running loop but no `--loop` scheduler):
```bash
cd stack
docker compose exec fdd-loop python -m openfdd_stack.platform.drivers.run_rule_loop
```
(`fdd-loop` image defaults to `run_rule_loop --loop`; this overrides the command for a single run. From the repo you can also use `python tools/run_rule_loop.py` on the host with `OFDD_DB_DSN` set.)

**Summary:** For “update faults now” with the normal Docker loop, use **touch** (or the script or `POST /run-fdd`). For a single run without the loop, use the **Py script** (or the exec command above).

---

## Throttling and rate limiting

1. **No API rate limiting by default** — The API does not throttle incoming requests. Clients can call as often as they like unless you add rate limiting elsewhere.
2. **OT/building network is paced** — Outbound traffic to the building is throttled by configuration: BACnet scraper polls on an interval (e.g. every 5 minutes), the FDD loop runs on a schedule (e.g. every 3 hours), and the weather scraper runs on an interval (e.g. daily). We do not continuously hammer the BACnet or OT network; you can tune these intervals in platform config.
3. **Adding incoming rate limiting** — To limit how often external clients can call the API (e.g. for a busy integration or to protect the OT network), add rate limiting at the reverse proxy (e.g. Caddy with a rate-limit module) or with middleware. See [Security — Throttling and rate limiting](../security#throttling-and-rate-limiting).

---

## Resource check

```bash
free -h && uptime && echo "---" && docker stats --no-stream 2>/dev/null
```

---

## Database

```bash
cd stack
docker compose exec db psql -U postgres -d openfdd -c "\dt"
```

---

## Grafana (datasource + cookbook)

Only the TimescaleDB datasource is provisioned. To build dashboards and SQL for BACnet, faults, weather, or system resources, see [Grafana SQL cookbook](grafana_cookbook).

---

## Unit tests and formatter

```bash
# From repo root (install once: pip install -e ".[dev]")
.venv/bin/python -m pytest open_fdd/tests/ -v
.venv/bin/python -m black .
```

See [Quick reference](quick_reference) for a one-page cheat sheet.
