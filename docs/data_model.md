---
title: Data Model & Brick
nav_order: 12
---

# Data Model & Brick

open-fdd can run **BRICK model driven**: rule inputs are resolved from a Brick TTL instead of hardcoded column names. The Brick model maps BMS points to open-fdd rule inputs via `ofdd:mapsToRuleInput`, `rdfs:label`, and optionally `ofdd:equipmentType` for equipment-specific rule filtering.

**Prerequisite:** Complete [SPARQL & Validate Prereq]({{ "sparql_validate_prereq" | relative_url }}) — test SPARQL and run validation before running faults.

## Run all applicable rules

```bash
python examples/run_all_rules_brick.py
# or:
python examples/run_all_rules_brick.py --ttl brick_model.ttl --rules my_rules --csv data_ahu7.csv
python examples/run_all_rules_brick.py --validate-first   # run validation before faults
```

The runner loads the Brick TTL, resolves the column map, filters rules by equipment type, and runs `RuleRunner`. Use `--validate-first` to run validation before faults.

**Example output:**

```bash
> python examples/run_all_rules_brick.py --validate-first 
=== Brick Data Model Validation ===

TTL: C:\Users\ben\Documents\open-fdd\examples\brick_model.ttl
Rules: C:\Users\ben\Documents\open-fdd\examples\my_rules

Validates: Can open-fdd run your rules against your CSV using this Brick model?

1. SPARQL test (prereq)
   Checks: TTL parses; points have ofdd:mapsToRuleInput + rdfs:label (Brick->CSV mapping)
   OK

2. Brick model (column map, equipment types)
   Checks: Resolved Brick class -> CSV column; equipment_type for rule filtering
   Column map: 22 mappings (Brick class -> CSV column)
   Equipment types: ['VAV_AHU']

3. Rules vs model
   Checks: Each rule input (brick class) has a mapping; 6 rules loaded
   All applicable rule inputs mapped

4. Brick schema (SHACL) - skipped (pip install brickschema to validate ontology)

=== VALIDATION PASSED ===

Data model and rules are ready. Run: python run_all_rules_brick.py
Loading Brick model...
  Column map: 22 mappings
  Equipment types: ['VAV_AHU']
Loading rules...
  Loaded 6 rules, 6 apply to this equipment
Loading CSV...

Ran 6 rules. Flag columns: ['rule_a_flag', 'rule_b_flag', 'rule_c_flag', 'hunting_flag', 'bad_sensor_flag', 'flatline_flag']
  rule_a_flag: 409 fault samples
  rule_b_flag: 1826 fault samples
  rule_c_flag: 31 fault samples
  hunting_flag: 717 fault samples
  bad_sensor_flag: 3146 fault samples
  flatline_flag: 3926 fault samples

Output saved to C:\Users\ben\Documents\open-fdd\examples\run_all_rules_output.csv

```

---

## Where the TTL came from

`examples/brick_model.ttl` was created from:

1. **BAS AHU screenshot** — A BMS graphic of AHU 7 (Williams Peak School District, Elementary School). The screenshot shows points like SAT (°F), OAT (°F), OA Damper Cmd (%), etc.
2. **CSV export** — Time-series data downloaded from the BAS with column headers matching those labels.
3. **Brick modeling** — Each BMS point was mapped to a Brick class (e.g. `Supply_Air_Temperature_Sensor`, `Outside_Air_Temperature_Sensor`) and given `rdfs:label` = the CSV column name and `ofdd:mapsToRuleInput` = the open-fdd rule input name.

So the TTL is the **semantic bridge** between that BAS/BMS schema and open-fdd’s rule inputs.

---

## Brick TTL structure

```turtle
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix : <http://openfdd.local/ahu7#> .

:ahu_7 a brick:Air_Handling_Unit ;
    rdfs:label "AHU 7" ;
    ofdd:equipmentType "VAV_AHU" .    # Used to filter rules

:oat_sensor a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "OAT (°F)" ;           # CSV column name
    brick:isPointOf :ahu_7 ;
    ofdd:mapsToRuleInput "oat" .      # open-fdd rule input

:sat_sensor a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "SAT (°F)" ;
    brick:isPointOf :ahu_7 ;
    ofdd:mapsToRuleInput "sat" .

:oa_damper_cmd a brick:Damper_Position_Command ;
    rdfs:label "OA Damper Cmd (%)" ;
    brick:isPointOf :ahu_7 ;
    ofdd:mapsToRuleInput "economizer_sig" .
```

- **`rdfs:label`** — Matches the CSV column header (e.g. `"OAT (°F)"`).
- **`ofdd:mapsToRuleInput`** — Rule input name used in YAML (e.g. `oat`, `sat`, `economizer_sig`). When the same Brick class appears multiple times (e.g. two `Valve_Command`), this disambiguates.
- **`ofdd:equipmentType`** — Equipment type string (e.g. `"VAV_AHU"`, `"AHU"`). Rules with `equipment_type: [VAV_AHU]` only run when the Brick model declares that equipment type.

---

## equipment_type matching

YAML rules can declare `equipment_type`:

```yaml
# ahu_rule_a.yaml (or duct static rule)
equipment_type: [VAV_AHU]
```

The Brick model declares equipment types on equipment entities:

```turtle
:ahu_7 a brick:Air_Handling_Unit ;
    ofdd:equipmentType "VAV_AHU" .
```

**Matching logic:**

- If a rule has **no** `equipment_type`, it runs for all equipment.
- If a rule has `equipment_type: [VAV_AHU, AHU]`, it runs only when the Brick model has at least one of those types.
- If the Brick model has **no** `ofdd:equipmentType`, all rules run (no filtering).

---

## brick_resolver — column map keys

`open_fdd.engine.brick_resolver.resolve_from_ttl()` returns a dict keyed by **Brick class names** (and `BrickClass|rule_input` for disambiguation):

| Key | Value | When |
|-----|-------|------|
| `Supply_Air_Temperature_Sensor` | `"SAT (°F)"` | Single Brick class |
| `Valve_Command\|heating_sig` | `"Prht Vlv Cmd (%)"` | Duplicate Brick class, disambiguated by rule_input |
| `Valve_Command\|cooling_sig` | `"Clg Vlv Cmd (%)"` | Same |
| `oat` | `"OAT (°F)"` | Backward compat: rule_input → label |

`RuleRunner` uses this to resolve rule inputs: for each input with `brick: Valve_Command` and `column: heating_sig`, it looks up `Valve_Command|heating_sig` in the column map.

---

## BRICK external data references (ref:)

Brick v1.2 adds `ref:hasExternalReference` for timeseries storage. A point can link to a database row:

```turtle
:oat_sensor a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "OAT (°F)" ;
    ofdd:mapsToRuleInput "oat" ;
    ref:hasExternalReference [
        a ref:TimeseriesReference ;
        ref:hasTimeseriesId "uuid-of-db-row" ;
        ref:storedAt :database ;
    ] .
```

- **`ref:hasTimeseriesId`** — ID in your timeseries DB (e.g. TimescaleDB row UUID).
- **`ref:storedAt`** — Reference to the database instance.

open-fdd-core uses this when ingesting CSV: it creates points in the DB, then generates TTL with `ref:hasTimeseriesId` = point UUID. The Brick model then points directly at the stored data.

---

## Manual vs Brick mapping

| Approach | When |
|----------|------|
| **Manual** | Small script, known columns: `column_map = {"oat": "OAT (°F)", "sat": "SAT (°F)"}` |
| **Brick** | BAS/BMS with a Brick TTL: `column_map = resolve_from_ttl("model.ttl")` |

`RuleRunner.run(column_map=...)` accepts any `{Brick_class_or_rule_input: df_column}` dict.

---

## End-to-end framework: open-fdd-datalake

For real BAS trend exports (zip-of-zips, messy CSVs), use [open-fdd-datalake](https://github.com/bbartling/open-fdd-datalake). It ingests data, builds Brick TTL from an equipment catalog, runs open-fdd rules, and produces client docx reports. Clone it as a framework for building-specific FDD projects.

---

**Next:** [Fault Visualization & Zooming]({{ "fault_visualization" | relative_url }}) — zoom in on fault events, IPython notebook
