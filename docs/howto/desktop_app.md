# Open-FDD Desktop App

## Goal

Run Open-FDD as a pure Python desktop app with no web server and no Docker runtime.

This repository now includes a Tauri + React desktop UI workspace at `apps/desktop-ui` that talks to a local Python bridge.
The desktop app is under active construction; core ingest/model/rules paths are working, while UX and packaging continue to evolve.

## Install

```bash
pip install "open-fdd[desktop]"
```

## Launch

### Tauri + React desktop UI

```bash
# terminal 1
open-fdd-desktop-bridge

# terminal 2
cd apps/desktop-ui
npm install
npm run dev
```

### Desktop bridge Swagger/OpenAPI

Once bridge is running locally:

- Swagger UI: `http://127.0.0.1:8765/docs`
- OpenAPI JSON: `http://127.0.0.1:8765/openapi.json`

Use Swagger for endpoint discovery, request body examples, and quick local API testing for OpenClaw or other assistants.

## Data ingest quickstart (desktop bridge API)

Base URL:

- `http://127.0.0.1:8765`

### 1) Create or list sites

```bash
curl http://127.0.0.1:8765/sites
curl -X POST http://127.0.0.1:8765/sites -H "Content-Type: application/json" -d "{\"name\":\"HQ\"}"
```

### 2) CSV ingest (file path or upload)

```bash
# direct path
curl -X POST http://127.0.0.1:8765/ingest/csv \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"source\":\"csv\",\"csv_path\":\"C:/data/site.csv\"}"
```

```bash
# multipart upload
curl -X POST http://127.0.0.1:8765/ingest/csv/upload \
  -F "site_id=<site-id>" \
  -F "source=csv" \
  -F "file=@C:/data/site.csv"
```

### 3) Open-Meteo weather ingest

```bash
# set weather config once
curl -X POST http://127.0.0.1:8765/config/weather \
  -H "Content-Type: application/json" \
  -d "{\"latitude\":42.36,\"longitude\":-71.06,\"timezone\":\"America/New_York\",\"base_url\":\"https://archive-api.open-meteo.com/v1/archive\"}"

# ingest weather rows
curl -X POST http://127.0.0.1:8765/ingest/weather \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"days_back\":7}"
```

### 4) Onboard ingest

```bash
curl -X POST http://127.0.0.1:8765/ingest/onboard \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\"}"
```

### 5) BACnet ingest (one-shot) and polling

```bash
# one-shot pull
curl -X POST http://127.0.0.1:8765/ingest/bacnet \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"server_url\":\"http://192.168.204.18:8080\",\"api_key\":\"<token>\"}"

# enable 5-minute poll loop
curl -X POST http://127.0.0.1:8765/config/bacnet \
  -H "Content-Type: application/json" \
  -d "{\"enabled\":true,\"interval_seconds\":300,\"site_id\":\"<site-id>\",\"server_url\":\"http://192.168.204.18:8080\",\"api_key\":\"<token>\"}"
```

### 6) Join sources for analysis/plots

```bash
curl -X POST http://127.0.0.1:8765/timeseries/query \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"sources\":[\"csv\",\"weather\",\"onboard\",\"bacnet\"],\"join_on_timestamp\":true,\"join_how\":\"outer\",\"limit\":10000}"
```

## CSV timestamp parsing expectations

Desktop CSV ingest is strict enough to catch bad files but flexible on common field formats:

- Timestamp column auto-detection prefers `timestamp`, then other time/date-like headers.
- Known timezone abbreviations like `EDT`, `EST`, `CDT`, `PDT`, etc. are normalized to UTC offsets before parsing.
- Parsing uses UTC-normalized datetimes and drops rows with unparseable timestamps.
- A minimum valid timestamp ratio is enforced; files with mostly bad timestamps return a clear validation error instead of silently importing junk data.

Recommended CSV practice:

- Include a dedicated timestamp column (`timestamp` preferred).
- Use ISO 8601 when possible (example: `2026-03-18T21:00:00-04:00`).
- Avoid mixed timestamp formats inside one file.

If import fails, fix timestamp formatting and retry.

## Data model + BRICK

- Desktop stores model data in user-writable app-data (`open-fdd-desktop/model.json`).
- BRICK TTL is generated to `open-fdd-desktop/data_model.ttl`.
- App-data root is platform-specific (`%APPDATA%` on Windows, `~/.local/share` on Linux, `~/Library/Application Support` on macOS) and is resolved by `open_fdd.desktop.storage.paths.desktop_data_dir`.
- BRICK input mapping for rules resolves through `open_fdd.desktop.services.BrickService`.

## Feather-first ingestion

- CSV, weather, and onboard drivers write pandas frames into timestamped Feather files under `open-fdd-desktop/feather_store`.
- Feather path layout is source/site scoped:
  - `open-fdd-desktop/feather_store/<safe_source>/<safe_site_id>/<timestamp>_<nonce>.feather`
- Storage remains append/chunk based (many files per site/source) for reliability and backfill workflows.
- The desktop bridge can still present a site-level joined view for plotting (multi-source virtual merge by timestamp), so operators get a single logical trend frame without rewriting raw files.
- Time-series reads for rules concatenate all Feather files for a selected `(source, site_id)` pair.
- Point metadata supports external refs like:
  - `feather://<source>/<site_id>/<metric>`
- These refs are persisted in the model and emitted in TTL via `ofdd:externalReference`.

## Rule loop behavior

- `open_fdd.desktop.rules.run_rule_loop_batched` executes rules with memory-aware chunking.
- If data fits available memory target, full-frame evaluation is used.
- Otherwise, DataFrames are chunked and processed with equivalent rule semantics.
- Chunk size can be user-forced from desktop (`chunk_rows`) or auto-estimated from available memory.
- Batched outputs are concatenated back into one result frame so downstream fault summaries behave the same as single-pass runs.

## Typical desktop workflow (current)

1. Create/select a site in the desktop model tab.
2. Ingest data (CSV import, weather fetch, or onboard scrape) into Feather-backed storage.
3. Confirm points and external references in model + generated BRICK TTL.
4. Run rules from a local YAML rules directory.
5. For large datasets, use batched rule execution (`chunk_rows` > 0, or leave auto-estimation on).
6. Review fault columns and summaries from the merged output frame.

## Development

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -U pip
pip install -e ".[dev,desktop]"
pytest
```

