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

### Python shell

```python
import open_fdd
open_fdd.GUI()
```

### CLI

```bash
open-fdd-desktop
```

### Tauri + React desktop UI

```bash
# terminal 1
open-fdd-desktop-bridge

# terminal 2
cd apps/desktop-ui
npm install
npm run dev
```

## Data model + BRICK

- Desktop stores model data in user-writable app-data (`open-fdd-desktop/model.json`).
- BRICK TTL is generated to `open-fdd-desktop/data_model.ttl`.
- App-data root is platform-specific (`%APPDATA%` on Windows, `~/.local/share` on Linux, `~/Library/Application Support` on macOS) and is resolved by `open_fdd.desktop.storage.paths.desktop_data_dir`.
- BRICK input mapping for rules resolves through `open_fdd.desktop.services.BrickService`.

## Feather-first ingestion

- CSV, weather, and onboard drivers write pandas frames into timestamped Feather files under `open-fdd-desktop/feather_store`.
- Feather path layout is source/site scoped:
  - `open-fdd-desktop/feather_store/<safe_source>/<safe_site_id>/<timestamp>_<nonce>.feather`
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

