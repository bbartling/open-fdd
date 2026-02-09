# Analyst Area — Rule Tuning & FDD Pipeline

Run FDD on heat pump data (e.g. SP_Data.zip), tune rules via YAML, validate Brick model with SPARQL.

## Setup

1. From monorepo root: `pip install -e .`
2. Place `SP_Data.zip` in `analyst/` (or set `SP_DATA_ZIP` env)
3. Run from `analyst/`: `./run_all.sh`

## Pipeline

1. **Ingest** — Extract equipment catalog from zip-of-zips
2. **To DataFrame** — Build `data/heat_pumps.csv` (sat, zt, fan_status)
3. **Brick Model** — Generate `data/brick_model.ttl`
4. **SPARQL** — Validate data model (points, equipment, completeness)
5. **Run FDD** — Apply rules, write `reports/fault_summary.csv`, `reports/heat_pump_report.txt`

## Tuning Rules

Edit YAML in `analyst/rules/` to tune params (e.g. `min_discharge_temp`, `window`). The pipeline uses these rules when present; otherwise falls back to `open_fdd/rules/`.
