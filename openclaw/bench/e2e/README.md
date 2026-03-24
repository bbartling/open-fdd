# Optional E2E and long-run bench

These scripts are **not** run by `./scripts/bootstrap.sh --test`. They target a **live** Open-FDD deployment (API + frontend + optional BACnet devices) and may require Selenium, long runtime, and secrets.

## Install

From repo root (with a venv):

```bash
pip install -r openclaw/bench/e2e/requirements-e2e.txt
```

## Orchestrator

[`automated_suite.py`](automated_suite.py) runs steps in sequence. Example (adjust URLs):

```bash
python openclaw/bench/e2e/automated_suite.py \
  --api-url http://127.0.0.1:8000 \
  --frontend-url http://127.0.0.1:5173 \
  --daytime-smoke
```

Use `--skip e2e` (etc.) to run a subset. See `--help` for flags.

## Individual scripts

| Script | Role |
|--------|------|
| `1_e2e_frontend_selenium.py` | Browser E2E against the React app |
| `2_sparql_crud_and_frontend_test.py` | SPARQL/API/UI parity |
| `3_long_term_bacnet_scrape_test.py` | Long BACnet scrape / fault checks |
| `4_hot_reload_test.py` | Rule hot-reload / faults UI smoke |

Set `OFDD_API_KEY` in the environment when the API requires Bearer auth.
