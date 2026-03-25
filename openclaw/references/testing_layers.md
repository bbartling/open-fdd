# Where testing lives (OpenClaw lab vs product)

Use this map so failures land in the **right bucket** in `issues_log.md` and GitHub issues.

## Primary entrypoint (not under `openclaw/`)

| What | Path / command |
|------|----------------|
| Stack + CI-style matrix | **`scripts/bootstrap.sh`** — full stack, **`--test`** (frontend in Docker + **host pytest** + Caddy), **`--mode collector|model|engine`**, **`--verify`**, optional **`--with-mcp-rag`**. |

**OpenClaw usually runs this first.** Host needs **`.venv`** + **`pip install -e ".[dev]"`** for backend pytest (see `openclaw/README.md`).

## Under `open-fdd/openclaw/` (lab / bench)

| Location | Role | When it fails, log as… |
|----------|------|-------------------------|
| **`openclaw/scripts/`** | Small helpers (`capture_bootstrap_log.sh`, …) | area: **bootstrap** / **tooling** |
| **`openclaw/bench/e2e/`** | Heavy Python: `1_e2e_frontend_selenium.py`, `2_sparql_crud_and_frontend_test.py`, `3_long_term_bacnet_scrape_test.py`, `4_hot_reload_test.py`, **`automated_suite.py`** | area: **e2e**, **sparql**, **bacnet**, **hot-reload** — cite log file |
| **`openclaw/bench/scripts/`** | e.g. **`monitor_fake_fault_schedule.py`** | area: **bacnet** / **bench** |
| **`openclaw/bench/fake_bacnet_devices/`** | Fake devices + **`fault_schedule.py`** | area: **fake_bacnet** |
| **`openclaw/windows/`** | `.cmd` overnight/daytime wrappers | area: **windows_bench** |
| **`openclaw/bench/sparql/`** | `.sparql` fixtures (manual / semi-auto) | area: **sparql** / **graph** |

## Product / CI backend (pytest)

| What | Path |
|------|------|
| API/platform tests | **`open_fdd/tests/`** (+ paths in **`pyproject.toml`**) |
| Run | **`pytest`** or **`./scripts/bootstrap.sh --test`** (uses host `.venv` python) |

Log as area: **backend** / **platform** with test node id.

## Docs

| What | Path |
|------|------|
| Lab layout | **`openclaw/README.md`** |
| Broader plan | **`docs/operations/testing_plan.md`** |

## What to write in `issues_log.md` (durable after browser closes)

Each bullet should help **you** and **Cursor** the next day:

- **date**, **area** (from table above), **symptom**, **command or script**, **log path** under `openclaw/logs/…`, **suspected cause**, **GitHub issue** if filed.
- Separate **OpenClaw/agent mistakes** (wrong `cd`, no venv) from **Open-FDD product bugs** (API 500, wrong fault).

## What belongs in GitHub Issues (bbartling/open-fdd)

- Regressions in **product** behavior, security notes, doc bugs worth tracking.
- Keep **`issues_log.md`** as the **fast lab trail**; promote stable items to Issues.
