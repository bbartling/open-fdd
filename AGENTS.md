# Agent Guidelines — Open-FDD

Guidance for AI assistants working on **Open-FDD**, an open-source edge analytics platform for smart buildings.

---

## Project Summary

Open-FDD ingests BACnet and Open-Meteo telemetry, stores it in TimescaleDB, and runs YAML-defined FDD rules. It exposes REST APIs and Grafana dashboards. Deployable behind the firewall; cloud-agnostic.

**Stack:** API (FastAPI), Grafana, TimescaleDB, BACnet scraper, weather scraper, FDD loop, diy-bacnet-server. BACnet driver uses a **curated discovery CSV** (run discovery before starting the stack; see docs/bacnet). Rules are Brick-model driven (no column in YAML).

---

## Where to Look (ordered)

1. **docs/** — Main documentation: overview, BACnet (discovery → curated CSV → scrape), data modeling (sites, equipment, points), rules, API reference, security (Caddy)
2. **docs/api/platform.md** — REST API (sites, points, equipment, data-model)
3. **docs/api/engine.md** — RuleRunner, load_rule, run()
4. **docs/expression_rule_cookbook.md** — Expression rule recipes (Brick-only inputs)
5. **docs/configuration.md** — Platform YAML, env vars, rule YAML, edge limits, BACnet single/multi-gateway
6. **docs/bacnet/overview.md** — Discovery first (port 47808), curate CSV, then start scraper
7. **docs/standalone_csv_pandas.md** — Future standalone CSV/pandas FDD (PyPI); archived analyst workflows in analyst/README.md
8. **open_fdd/** — Source code; docstrings are ground truth

---

## Capabilities

- **Platform:** REST CRUD for sites, equipment, points; data-model export/import, TTL generation, SPARQL
- **Engine:** Load YAML rules, run RuleRunner against DataFrames. Resolution is **100% Brick-model driven:** rules declare Brick classes only (no `column` in YAML); column_map is built from Brick TTL via SPARQL (see resolve_from_ttl).
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

- Columns matching rule inputs via **column_map** (built from Brick TTL/SPARQL; rules do not declare `column` in YAML)
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
| **column_map** | Built from Brick TTL (SPARQL); maps Brick class (or Brick_class+rule_input for disambiguation) to DataFrame column. Rules declare only Brick classes; no `column` in YAML. |
| **external_id** | Raw point ID from source (e.g. BACnet object name) |

---

## Public API

- **Engine:** RuleRunner, load_rule, load_rules_from_dir, bounds_map_from_rule
- **Reports:** summarize_fault, summarize_all_faults, print_summary, get_fault_events, all_fault_events
- **Brick:** resolve_from_ttl, get_equipment_types_from_ttl (when rdflib available)
