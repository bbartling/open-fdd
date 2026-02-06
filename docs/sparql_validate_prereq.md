---
title: SPARQL & Validate Prereq
nav_order: 11
---

# SPARQL & Validate — Test Your Model First

Before running fault detection with a Brick model, you **test the model** and **validate** that rules map correctly. This prerequisite tutorial walks through testing SPARQL queries and running the validator.

## What is SPARQL?

**SPARQL** (SPARQL Protocol and RDF Query Language) is the standard query language for RDF data. Your Brick model is stored as RDF (Turtle `.ttl` format). SPARQL lets you ask questions like: *Which points have a Brick class and a CSV column label?*

open-fdd uses SPARQL internally to build the column map (Brick class → CSV column). If SPARQL fails against your TTL, fault detection will not work. Testing SPARQL first confirms the model structure is valid.

## 1. Run test_sparql.py

From the project root:

```bash
python examples/test_sparql.py --ttl brick_model.ttl
```

Or from the `examples/` directory:

```bash
python test_sparql.py --ttl brick_model.ttl
```

**Expected output:**

```
SPARQL OK. Sample rows (10):
  Outside_Air_Temperature_Sensor | OAT (°F) | oat
  Return_Air_Temperature_Sensor | RAT (°F) | rat
  Mixed_Air_Temperature_Sensor | MAT (°F) | mat
  Supply_Air_Temperature_Sensor | SAT (°F) | sat
  Supply_Air_Temperature_Setpoint | Eff SAT Sp (°F) | sat_setpoint
  Damper_Position_Command | OA Damper Cmd (%) | economizer_sig
  Valve_Command | Clg Vlv Cmd (%) | cooling_sig
  Valve_Command | Prht Vlv Cmd (%) | heating_sig
  Supply_Fan_Speed_Command | SF Spd Cmd (%) | supply_vfd_speed
  Supply_Air_Static_Pressure_Sensor | SA Static Press (inH₂O) | duct_static
```

Each row shows: **Brick class** | **CSV column (rdfs:label)** | **rule input (ofdd:mapsToRuleInput)**.

## 2. The SPARQL query (test_sparql.py)

The script runs this query against your Brick TTL:

```python
q = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?point ?brick_class ?label ?rule_input WHERE {
    ?point ofdd:mapsToRuleInput ?rule_input .
    ?point a ?brick_type .
    FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
    BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
    ?point rdfs:label ?label .
}
LIMIT 10
"""
```

**What it does:**

| Part | Meaning |
|------|---------|
| `?point ofdd:mapsToRuleInput ?rule_input` | Find points with open-fdd rule input mapping |
| `?point a ?brick_type` | Get the Brick class of each point |
| `FILTER(STRSTARTS(...))` | Only Brick-namespace types |
| `BIND(REPLACE(...))` | Extract short class name (e.g. `Supply_Air_Temperature_Sensor`) |
| `?point rdfs:label ?label` | Get CSV column name |

If this returns rows, your TTL has the structure open-fdd expects.

## 3. Run validate_data_model.py

After SPARQL works, run the full validator:

```bash
python examples/validate_data_model.py
# or with custom paths:
python examples/validate_data_model.py --ttl brick_model.ttl --rules my_rules
```

**What it validates:**

1. **SPARQL test** — Same as above; TTL parses, points have `ofdd:mapsToRuleInput` + `rdfs:label`
2. **Brick model** — Column map resolved; equipment types extracted
3. **Rules vs model** — Every rule input required by applicable rules has a mapping
4. **Brick schema (optional)** — `pip install brickschema` to validate against Brick ontology (SHACL)

**Example output (passed):**

```
=== Brick Data Model Validation ===

TTL: .../examples/brick_model.ttl
Rules: .../examples/my_rules

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
```

## 4. If validation fails

- **SPARQL test fails** — Fix the TTL: ensure points have `ofdd:mapsToRuleInput` and `rdfs:label`
- **Empty column map** — No points match the query; check Brick class and namespace
- **Rules vs model errors** — A rule needs an input (e.g. `Supply_Air_Static_Pressure_Setpoint`) that has no mapping in the TTL; add the point to the Brick model or adjust the rule

---

**Next:** [Data Model & Brick]({{ "data_model" | relative_url }}) — run faults, see outputs, Brick TTL structure
