# Open-FDD Desktop App

## Goal

Run Open-FDD as a pure Python desktop app with no web server and no Docker runtime.

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

## Data model + BRICK

- Desktop stores model data in user-writable app-data (`open-fdd-desktop/model.json`).
- BRICK TTL is generated to `open-fdd-desktop/data_model.ttl`.
- BRICK input mapping for rules resolves through `open_fdd.desktop.services.BrickService`.

## Feather-first ingestion

- CSV, weather, and onboard drivers write pandas frames into Feather files under `open-fdd-desktop/feather_store`.
- Point metadata supports external refs like:
  - `feather://<source>/<site_id>/<metric>`
- These refs are persisted in the model and emitted in TTL via `ofdd:externalReference`.

## Rule loop behavior

- `open_fdd.desktop.rules.run_rule_loop_batched` executes rules with memory-aware chunking.
- If data fits available memory target, full-frame evaluation is used.
- Otherwise, DataFrames are chunked and processed with equivalent rule semantics.

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

