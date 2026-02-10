# Analyst Area — Standalone CSV FDD Pipeline

**Standalone CSV workflow:** Run FDD on CSV/zip data (e.g. heat pump exports, SP_Data.zip) without using the platform database. Good for one-off analysis, tuning rules on exported CSVs, and validating Brick models with SPARQL.

For **time-series and database-driven** workflows (BACnet → TimescaleDB → Grafana, CRUD API, Brick data model on points), see the platform stack and **Data modeling** in [MONOREPO_PLAN.md](../MONOREPO_PLAN.md).

## Setup

1. From monorepo root: `pip install -e ".[brick]"`
2. Place `SP_Data.zip` in `analyst/` (or set `SP_DATA_ZIP` env)
3. Run from `analyst/`: `./run_all.sh`

## Pipeline

1. **Ingest** — Extract equipment catalog from zip-of-zips
2. **To DataFrame** — Build `data/heat_pumps.csv` (sat, zt, fan_status)
3. **Brick Model** — Generate `data/brick_model.ttl` from catalog (Brick classes, `rdfs:label` = DataFrame column names, `ofdd:mapsToRuleInput`)
4. **SPARQL** — Validate data model (points, equipment, completeness)
5. **Run FDD** — Apply rules, write `reports/fault_summary.csv`, `reports/heat_pump_report.txt`

## Tuning Rules

Edit YAML in `analyst/rules/`. The platform checks `datalake_rules_dir` (analyst/rules) first when loading rules; otherwise uses `open_fdd/rules/`. For DB-driven FDD, rules live in `open_fdd/rules/` and the data model comes from the DB (or a TTL in config); see MONOREPO_PLAN.
