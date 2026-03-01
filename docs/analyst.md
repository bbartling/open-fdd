---
title: Analyst area — Legacy & standalone
nav_order: 13
---

# Analyst Area — Legacy & Standalone Workflows

**Archived documentation for note purposes.** This page preserves the legacy static-CSV, AHU7 tutorial, and Brick-driven workflows that predate the current Open-FDD edge platform (TimescaleDB, Grafana, BACnet, Open-Meteo).

---

## Standalone CSV Workflow (Legacy)

**Standalone CSV pipeline:** Run FDD on CSV/zip data (e.g. heat pump exports, SP_Data.zip) without using the platform database. Good for one-off analysis, tuning rules on exported CSVs, and validating Brick models with SPARQL.

**Tools:** `analyst/run_all.sh`, `analyst/sparql/`, `analyst/rules/`, `open_fdd/analyst/` (ingest, to_dataframe, brick_model, run_fdd).

---

## Legacy Getting Started — AHU7 Tutorial

1. Clone the repo, create venv, `pip install -e ".[dev,brick]"`.
2. Download `data_ahu7.csv` to `examples/` (see [Examples](examples)).
3. Run `check_faults_ahu7_flatline.py` and `check_faults_ahu7_bounds.py`.
4. Rules live in `open_fdd/rules/` and `examples/my_rules/`.

**Rule types:** bounds · flatline · expression · hunting · oa_fraction · erv_efficiency.

---

## Legacy Rule Documentation (Archived)

### Bounds Rule
- Type `bounds` — flags sensor values outside `[low, high]`.
- Use `params={"units": "metric"}` for °C/Pa.
- Example: `bad_sensor_check`, `zone_temp_bounds`, `co2_bounds`, `rh_bounds`.
- Full rule: `open_fdd/rules/sensor_bounds.yaml`.

### Flatline Rule
- Type `flatline` — flags stuck sensors (rolling spread < tolerance).
- Params: `tolerance`, `window`.
- Example: `sensor_flatline`, `weather_temp_stuck`, `rh_flatline`, `co2_flatline`.

### Hunting Rule
- Type `hunting` — flags excessive AHU state changes (PID hunting).
- Inputs: economizer damper, supply fan VFD, heating valve, cooling valve.
- Params: `delta_os_max`, `ahu_min_oa_dpr`, `window`.

### OA Fraction Rule
- Type `oa_fraction` — OA fraction vs design airflow error.

### ERV Efficiency Rule
- Type `erv_efficiency` — ERV effectiveness out of range.

### Expression Rule
- Type `expression` — custom pandas/numpy expression.
- Input keys = BRICK class names for Brick compatibility.
- See [Expression Rule Cookbook](expression_rule_cookbook) for AHU, chiller, weather recipes.

---

## Legacy Data Model & Brick

**Brick model driven:** Rule inputs resolved from Brick TTL via `ofdd:mapsToRuleInput`, `rdfs:label`, `ofdd:equipmentType`.

**Scripts:**
```bash
python examples/test_sparql.py --ttl data_model.ttl
python examples/validate_data_model.py --ttl data_model.ttl --rules my_rules
python examples/run_all_rules_brick.py --validate-first
```

---

## Legacy SPARQL & Validation

**SPARQL** queries the Brick TTL. `validate_data_model.py` checks:
1. SPARQL test (TTL parses, points have ofdd:mapsToRuleInput + rdfs:label)
2. Brick model (column map, equipment types)
3. Rules vs model (all rule inputs mapped)
4. Brick schema (optional, brickschema)

---

## Current Platform (AFDD) vs Analyst

| Aspect | Analyst (legacy) | Platform (current) |
|--------|------------------|--------------------|
| Data source | CSV / zip | TimescaleDB |
| Ingestion | Manual / scripts | BACnet scraper, Open-Meteo |
| Brick TTL | Built from equipment catalog CSV | Generated from DB (sites, equipment, points) |
| FDD run | `run_all_rules_brick.py` | fdd-loop (periodic, hot-reload) |
| Viz | Jupyter notebook | Grafana |
| API | None | REST CRUD + Swagger |

**Project rules** live in `analyst/rules/*.yaml`. The platform FDD loop loads from here every run (hot reload). Edit YAML on host; trigger a run (or wait for schedule) and view results in Grafana. See [Fault rules overview](rules/overview) and [Configuration](configuration).
