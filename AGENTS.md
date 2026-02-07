# Agent Contract — open-fdd

You are an assistant operating on **open-fdd**, a config-driven FDD (Fault Detection and Diagnostics) library for HVAC systems. Follow these rules strictly.

---

## Capabilities

- **Load CSV → DataFrame → run rules → return DataFrame + summaries**
- Load YAML rules from `open_fdd/rules/` or custom paths
- Resolve columns from Brick TTL via `resolve_from_ttl()`
- Run `RuleRunner.run()` to add fault flag columns
- Call `summarize_fault()`, `print_summary()` for analytics
- Generate fault events, plot zoom charts, build reports (when dependencies available)

---

## Non-capabilities (strict)

- **Do not invent columns.** Only use columns that exist in the input DataFrame or that rules explicitly add.
- **Do not hallucinate rule names.** Rule names and flags come from YAML files. Check `open_fdd/rules/` or the cookbook.
- **Do not claim a function exists** unless it appears in `docs/api_reference.md` or `open_fdd/**` docstrings.
- **Do not assume optional dependencies** (rdflib, python-docx, matplotlib) are installed unless stated.

---

## Where to look (ordered)

1. **docs/api_reference.md** — Public API: RuleRunner, load_rule, reports, brick_resolver
2. **docs/expression_rule_cookbook.md** — Rule recipes (BRICK-based)
3. **docs/ai_agents.md** — Agent-oriented overview
4. **docs/knowledge-map.md** — Map of where info lives
5. **docs/dataframe-contract.md** — Input/output DataFrame requirements
6. **docs/configuration.md** — Rule types, YAML structure
7. **docs/config_schema.md** — Config schema (equipment types, rule structure)
8. **examples/** — Scripts and notebooks
9. **open_fdd/** — Source code; read docstrings for ground truth

---

## Data contracts

### Input DataFrame

- **Required:** Columns matching rule inputs (via `column` in YAML or `column_map`)
- **Optional:** `timestamp` column (default name; used for time-based checks)
- **Index:** Row index unused; use `timestamp_col` for ordering
- **Dtypes:** Numeric for sensor/command columns; timestamps parseable if provided

### Output columns

- **Fault flags:** One column per rule, named by `flag` in YAML (e.g. `rule_a_flag`, `hunting_flag`, `bad_sensor_flag`)
- **Values:** Boolean (True = fault at that timestamp)
- **Naming:** `*_flag` convention; no `fc1_flag` — use `rule_a_flag` etc. per cookbook

### Episodes

- **Episode:** Contiguous run of `True` for a flag. Use `get_fault_events()` or `all_fault_events()` from reports.
- **Severity:** Not defined in core; rules produce boolean only.

---

## Glossary

| Term | Meaning |
|------|---------|
| **flag** | Output column name; boolean, True = fault |
| **episode** | Contiguous timestamps where a flag is True |
| **rule** | YAML config: name, type, flag, inputs, params, expression |
| **equipment_type** | Filter for Brick: AHU, VAV_AHU, VAV, etc. Only rules whose equipment_type matches the model run |
| **mapping** | `column_map`: {BRICK_class or rule_input: DataFrame column name} |
| **rule_input** | Key in rule inputs; variable name in expression; often BRICK class |

---

## Public vs internal

- **Public:** `RuleRunner`, `load_rule`, `resolve_from_ttl`, `get_equipment_types_from_ttl`, `summarize_fault`, `summarize_all_faults`, `print_summary`, `get_fault_events`, `all_fault_events`, `analyze_bounds_episodes`, `analyze_flatline_episodes`, `bounds_map_from_rule`
- **Internal:** `open_fdd.engine.checks` (check_bounds, check_expression, etc.), `open_fdd.reports.fault_viz` internals — may change without notice
