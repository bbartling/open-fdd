# OpenClaw Phase 2: `git pull` → dashboard CSV → modeling → FDD

Use after the [initial smoke](OPENCLAW_MANUAL_SMOKE.md) works, or when you already have `open-fdd` cloned and want to **update from GitHub**, then **exercise the dashboard and deeper bridge features** (including merged time-series and FDD).

**Human expectation:** If ports `8765` / `8090` / `8080` are published to the host, you can open **`http://localhost:8080`**, **drop in a CSV** in the UI, and use **Data model** + **FDD** flows when the bridge returns healthy responses below. The agent can drive the same paths via `curl` for reproducibility.

---

## Prompt to paste into OpenClaw

```text
You are continuing Open-FDD validation inside this Linux/container shell (bash, git, curl). The repo may already exist at a path like /home/node/.openclaw/workspace/open-fdd — prefer that directory if present instead of re-cloning.

Goal: (1) git pull latest master (or the branch the human names), (2) refresh deps/build only if needed, (3) start or verify bridge + MCP + static UI, (4) prove dashboard-equivalent flows: site + CSV upload + plots + merged time-series + model export/SPARQL + default rules + FDD. Report pass/fail with URLs, curl snippets, and log tails. Stop on first hard failure unless the human asks to continue.

Do in order:

0) Paths and update
   - cd to the existing open-fdd repo (e.g. cd /home/node/.openclaw/workspace/open-fdd). If no repo, clone https://github.com/bbartling/open-fdd.git and cd open-fdd.
   - git status && git fetch origin && git pull origin master   (or: git pull origin <branch> if the human specifies another branch)
   - If bootstrap-desktop.sh fails with CRLF errors, run: dos2unix scripts/bootstrap-desktop.sh 2>/dev/null || sed -i 's/\r$//' scripts/bootstrap-desktop.sh

1) Dependencies / stack (skip heavy steps if unchanged and last run was recent)
   - If pyproject.toml, package-lock.json, or scripts/bootstrap-desktop.sh changed, or UI/build fails: bash scripts/bootstrap-desktop.sh --install-deps --no-launch
   - If MCP index missing or stale: source .venv/bin/activate && python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json
   - Start services: bash scripts/bootstrap-desktop.sh   (or only restart processes if already running — kill old nohup PIDs/logs if the human wants a clean start)
   - Tail last ~30 lines of .openfdd-bridge.log .openfdd-mcp.log .openfdd-ui.log

2) Health
   - curl -sS http://127.0.0.1:8765/health
   - curl -sS http://127.0.0.1:8090/health   (exact host: 127.0.0.1 — NOT 127.0.1)
   - curl -sS http://127.0.0.1:8080/ | head -n 5
   - Tell the human host URLs if Docker publishes ports (e.g. http://localhost:8080 for the UI).

3) Site + CSV (same as UI “upload”)
   - POST http://127.0.0.1:8765/sites with JSON {"name":"Phase2 Site"} — save site_id.
   - Create /tmp/phase2.csv with a parseable timestamp column (header `timestamp` preferred) and numeric metrics. For a quick FDD smoke aligned with bundled AHU/VAV rules, include columns the defaults expect (e.g. zone temp, duct static, fan, OAT-style columns) OR use a minimal CSV and accept that default rules may need column_map / different rules_path — document what you used.
   - POST multipart http://127.0.0.1:8765/ingest/csv/upload — form: site_id=<id>, source=csv, file=@/tmp/phase2.csv
   - GET http://127.0.0.1:8765/plots/frame?site_id=<id>&source=csv&limit=20 — expect rows/columns JSON.

4) Merged time-series (multi-driver merge-on-read; no merged Feather file)
   - GET http://127.0.0.1:8765/plots/site-frame?site_id=<id>&sources=csv,weather,onboard,bacnet&limit=50 — expect JSON with "sources" listing drivers that had data (weather may be empty until ingest).
   - Optional: POST http://127.0.0.1:8765/ingest/weather with JSON {"site_id":"<id>","days_back":1} if env/lat/long is set; re-hit plots/site-frame and note new columns like *_weather.
   - Optional: POST http://127.0.0.1:8765/timeseries/query with JSON joining multiple sources (see OpenAPI /docs for TimeseriesQueryBody: sources, join_on_timestamp, join_how).

5) Data modeling (API parity with dashboard)
   - GET http://127.0.0.1:8765/model/export — confirm sites/points.
   - POST http://127.0.0.1:8765/data-model/sparql with a small SELECT (e.g. list brick:Site) — must not 500.

6) FDD
   - GET http://127.0.0.1:8765/rules/defaults and POST /rules/defaults/install if needed; attach rule pack to site if the API exists (see /docs).
   - Single source: POST http://127.0.0.1:8765/rules/run with JSON including site_id, source "csv", rules_path from GET /rules (or installed defaults path), optional start_ts/end_ts. Expect input_rows, output_rows, fault_totals (keys may end in _flag or _fault), load_mode "single".
   - Merged drivers (if multiple sources have rows): POST /rules/run with JSON including "sources": ["csv","weather"] (and join_how "outer" if desired). Expect load_mode "merged" and suffixed metric columns (e.g. sat_csv, oat_weather) — rules/YAML must reference those names or use column_map; if 500 due to missing columns, classify as data/rules mismatch not stack failure.

7) Deliverable
   - Table: step → pass/fail → evidence (HTTP code or JSON field).
   - One paragraph for the human: “Ready to drop CSV in dashboard?” — yes if health + upload + plots/frame succeed; FDD yes if /rules/run returns 200 with sensible rows; note any gap (ports, column names vs default rules, merge suffixes).

Constraints: use 127.0.0.1 (not 127.0.1). Do not invent API keys. Do not pkill broad patterns that kill your own shell.
```

---

## Quick notes (human)

| Topic | Detail |
|--------|--------|
| **Ready for dashboard CSV?** | Yes, once **`/health`**, **`/ingest/csv/upload`**, and **`/plots/frame`** work for your `site_id`. Open **`http://localhost:8080`** (or published host port). |
| **Ready for default-bundle FDD?** | Only if the CSV (or **column_map**) matches what the YAML rules expect; otherwise install defaults and use a CSV with the right logical columns, or custom `rules_path`. |
| **Merged `POST /rules/run`** | Pass **`"sources": ["csv","weather",...]`**; metrics become **`metric_sourcetag`** when 2+ drivers contribute rows. Single-source **`source":"csv"`** unchanged. |

See also: [OPENCLAW_MANUAL_SMOKE.md](OPENCLAW_MANUAL_SMOKE.md) for first-time clone + bootstrap + MCP index. **BACnet + DIY server:** [OPENCLAW_BACNET_DIY_SERVER.md](OPENCLAW_BACNET_DIY_SERVER.md).
