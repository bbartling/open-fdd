---
title: E2E frontend tests (Selenium)
parent: How-to Guides
nav_order: 55
---

# E2E frontend tests (Selenium)

End-to-end tests drive the **Open-FDD React frontend** in a real browser using Selenium. All actions (delete sites, create site, import payload, open Plots/Weather) are performed **via the UI**; the test does not call the API directly. This replaces or complements the API-only scripts (`delete_all_sites_and_reset.py`, `graph_and_crud_test.py`) when you want to validate the frontend and ensure **charts are not blank** (and, when data exists, show data).

---

## Prerequisites

- **Stack running:** Frontend (e.g. http://localhost:5173) and API (e.g. http://localhost:8000). Start with `./scripts/bootstrap.sh` or your usual stack.
- **Python:** Use a virtual environment (e.g. `python3 -m venv .venv && source .venv/bin/activate`), then `pip install -e ".[e2e]"` (adds `selenium`, `webdriver-manager`). Chrome/Chromium must be installed on the machine; the script uses `webdriver-manager` to fetch ChromeDriver. If you see “cannot find Chrome binary”, install Chromium (e.g. `apt install chromium-browser`) or Chrome.
- **CI:** E2E tests are **not** run in GitHub Actions (no Chrome, no running stack). CI runs the same checks as `./scripts/bootstrap.sh --test`: frontend lint + typecheck, backend pytest, Caddy validate.
- **Stack on Linux, browser on Windows:** You can run the script on a Windows PC (with Chrome) and point it at the stack on your Linux dev machine: use `--frontend-url http://<linux-ip>:5173` (or `:80` if you use Caddy). Same switch/LAN is enough; no need to run Selenium on the Linux box if it doesn’t have Chrome.

---

## Run the full flow

From the repo root, with the stack up:

```bash
pip install -e ".[e2e]"
python scripts/e2e_frontend_selenium.py
```

This will:

1. **Delete all sites and reset the graph** — Data model page → type the site count in the confirm box → click “Remove all sites and reset graph”.
2. **Create a site** — Add site “TestBenchSite” (or `TESTBENCH_SITE_NAME`) from the Data model page.
3. **Import LLM payload** — Paste `scripts/demo_site_llm_payload.json` (with `site_id` set to the created site) and click Import.
4. **Validate Plots** — Open Plots, select the site and at least one point, then assert the chart area has Recharts curve/path (and, when timeseries data exists, that the path has data).
5. **Validate Weather** — Open Weather and assert at least one chart panel is present and not broken.
6. **Overview** — Smoke-check that the overview page loads.

---

## Options

| Option | Description |
|--------|-------------|
| `--frontend-url URL` | Frontend base URL (default: `http://localhost:5173` or `FRONTEND_URL`). |
| `--headed` | Run the browser in headed mode (default: headless). |
| `--only delete-all` | Only run delete-all-sites and reset. |
| `--only create-and-import` | Only create site and import payload (then run chart checks). |
| `--only charts` | Only validate Plots and Weather charts (assumes site and data already exist). |
| `--skip-chart-data` | Do not assert that charts have data; only that pages and chart containers load. |

Examples:

```bash
# Only reset the data model via UI
python scripts/e2e_frontend_selenium.py --only delete-all

# Only check that charts render (site/data already present)
python scripts/e2e_frontend_selenium.py --only charts

# Use Caddy as entry point
FRONTEND_URL=http://localhost:8088 python scripts/e2e_frontend_selenium.py
```

---

## Chart validation (not blank)

- **Plots:** The test opens Plots, selects the test site and a point, then waits for a Recharts curve/path (`.recharts-curve` or `.recharts-line-curve`). If the path’s `d` attribute has length &gt; 20, the chart is considered to have data. If no path appears in time, it accepts the “No point data in this range” or “Select points” message as valid (chart rendered, no timeseries yet).
- **Weather:** The test ensures the Weather page has at least one Recharts wrapper/path; if paths exist, it checks that at least one has a non-empty `d` attribute.

For charts to “flood with data,” timeseries must exist (e.g. BACnet scraper has run, or weather scraper). Without that, the test still passes as long as the chart area renders and is not broken.

---

## Data model and test IDs

The Data model page uses a few `data-testid` and `data-site-id` attributes so the test can reliably find the delete-all confirm input, “Remove all sites” button, import textarea, Import button, Add site button, new site name input, and the site table row (to read `data-site-id` after creating a site). These are the only frontend changes for E2E; see `frontend/src/components/pages/DataModelPage.tsx`.

---

## API auth: why E2E might see “No sites to delete”

The E2E script replicates **delete_all_sites_and_reset.py** and **graph_and_crud_test.py** in the browser. The frontend **does** have the “Remove all sites and reset graph” feature (Data Model → Graph actions card). That block is only rendered when the frontend has at least one site — i.e. when **GET /sites** succeeds.

If your API requires Bearer auth (`OFDD_API_KEY` in `stack/.env`), the frontend must send that key. The frontend reads **VITE_OFDD_API_KEY** at build/serve time (same value as `OFDD_API_KEY`). When you run the stack with `docker compose`, the frontend container gets `VITE_OFDD_API_KEY: ${OFDD_API_KEY:-}` from `.env`, so the UI can fetch sites. If you serve the frontend some other way (e.g. a static build or another host) **without** setting `VITE_OFDD_API_KEY`, then GET /sites returns 401, the UI has 0 sites, and the delete-all section never appears — the E2E will report “No sites to delete” and print a hint.

**Fix:** Ensure the frontend is built or served with `VITE_OFDD_API_KEY` set to the same value as `OFDD_API_KEY` in `stack/.env`. When using the repo stack, `./scripts/bootstrap.sh` writes `OFDD_API_KEY` to `stack/.env` and the frontend container receives it; no extra step needed.

---

## Relation to API scripts

- **`scripts/delete_all_sites_and_reset.py`** — Same outcome (delete all sites, reset graph) but via **API** (GET /sites, DELETE /sites/{id}, POST /data-model/reset). Use it when you want a quick reset from the command line without opening the UI.
- **`scripts/graph_and_crud_test.py`** — Full CRUD + SPARQL + import test via **API** only. Use it for fast, headless API coverage.
- **`scripts/e2e_frontend_selenium.py`** — Same high-level flow (reset, create site, import payload, validate) but **via the frontend** and with **chart checks**. Use it to confirm the UI and charts behave correctly.

You can run the API scripts and the Selenium script in the same project; they do not conflict.
