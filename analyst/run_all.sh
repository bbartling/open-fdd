#!/bin/bash
# Full pipeline: ingest → Brick → SPARQL → FDD → reports.
# Run from analyst/ with SP_Data.zip present (or set SP_DATA_ZIP).
# Requires: pip install -e .. (open-fdd from monorepo)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

python3 -c "
from pathlib import Path
from open_fdd.analyst.config import default_analyst_config
from open_fdd.analyst import run_ingest, run_to_dataframe, run_brick_model, run_fdd_pipeline, run_sparql_main

cfg = default_analyst_config(Path.cwd())
print('=== 1. Ingest ===')
run_ingest(cfg)
print('=== 2. To DataFrame ===')
run_to_dataframe(cfg)
print('=== 3. Brick Model ===')
run_brick_model(cfg)
print('=== 4. SPARQL (data model check) ===')
run_sparql_main(config=cfg)
print('=== 5. Run FDD ===')
run_fdd_pipeline(cfg)
print('=== Done. Reports: reports/ ===')
"
