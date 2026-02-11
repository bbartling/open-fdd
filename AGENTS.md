# Agent Guidelines — Open-FDD

Guidance for AI assistants working on **Open-FDD**, an open-source edge analytics platform for smart buildings.

---

## Project Summary

Open-FDD ingests BACnet and Open-Meteo telemetry, stores it in TimescaleDB, and runs YAML-defined FDD rules. It exposes REST APIs and Grafana dashboards. Deployable behind the firewall; cloud-agnostic.

**Stack:** API (FastAPI), Grafana, TimescaleDB, BACnet scraper, weather scraper, FDD loop, diy-bacnet-server.

---

## Where to Look (ordered)

1. **docs/** — Main documentation: overview, concepts, BACnet, modeling, rules, API reference
2. **docs/api/platform.md** — REST API (sites, points, equipment, data-model)
3. **docs/api/engine.md** — RuleRunner, load_rule, run()
4. **docs/expression_rule_cookbook.md** — Expression rule recipes
5. **docs/configuration.md** — Platform YAML, env vars, rule YAML
6. **analyst/README.md** — Legacy CSV/analyst workflows (archived)
7. **open_fdd/** — Source code; docstrings are ground truth

---

## Capabilities

- **Platform:** REST CRUD for sites, equipment, points; data-model export/import, TTL generation, SPARQL
- **Engine:** Load YAML rules, run RuleRunner against DataFrames, resolve columns via Brick TTL or column_map
- **Rules:** bounds, flatline, expression, hunting, oa_fraction, erv_efficiency
- **Reports:** summarize_fault, print_summary, get_fault_events, all_fault_events (when dependencies available)

---

## Non-capabilities (strict)

- **Do not invent columns.** Only use columns that exist in the input DataFrame or that rules add.
- **Do not hallucinate rule names.** Rule names and flags come from YAML. Check `open_fdd/rules/` or `analyst/rules/`.
- **Do not claim a function exists** unless it appears in `open_fdd/**` or the docs.
- **Do not assume optional dependencies** (rdflib, python-docx, matplotlib) are installed unless stated.

---

## Data Contracts

### Input DataFrame (Engine)

- Columns matching rule inputs (via `column` in YAML or `column_map`)
- Optional `timestamp` column (default name)
- Numeric dtypes for sensor/command columns

### Output (Engine)

- Fault flag columns: `*_flag`, boolean, True = fault
- One column per rule

### API

- Sites, equipment, points: JSON CRUD
- Data-model: export (JSON), import (JSON), ttl (text/turtle), sparql (POST with query)

---

## Glossary

| Term | Meaning |
|------|---------|
| **flag** | Output column name; boolean, True = fault |
| **episode** | Contiguous timestamps where a flag is True |
| **rule_input** | Key in rule inputs; variable in expression; often BRICK class |
| **column_map** | {rule_input or BRICK_class: DataFrame column name} |
| **external_id** | Raw point ID from source (e.g. BACnet object name) |

---

## Public API

- **Engine:** RuleRunner, load_rule, load_rules_from_dir, bounds_map_from_rule
- **Reports:** summarize_fault, summarize_all_faults, print_summary, get_fault_events, all_fault_events
- **Brick:** resolve_from_ttl, get_equipment_types_from_ttl (when rdflib available)
