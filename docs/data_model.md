---
title: Data Model & Brick
nav_order: 6
---

# Data Model & Brick

open-fdd can run **BRICK model driven**: rule inputs are resolved from a Brick TTL instead of hardcoded column names. The Brick model maps BMS points to open-fdd rule inputs via `ofdd:mapsToRuleInput` and `rdfs:label`.

## Where the TTL came from

`examples/ahu7_brick_model.ttl` and `examples/rtu7_snip.png` were created from:

1. **BAS AHU screenshot** — A BMS graphic of AHU 7 (Williams Peak School District, Elementary School). The screenshot shows points like SAT (°F), OAT (°F), OA Damper Cmd (%), etc.
2. **CSV export** — Time-series data downloaded from the BAS with column headers matching those labels.
3. **Brick modeling** — Each BMS point was mapped to a Brick class (e.g. `Supply_Air_Temperature_Sensor`, `Outside_Air_Temperature_Sensor`) and given `rdfs:label` = the CSV column name and `ofdd:mapsToRuleInput` = the open-fdd rule input name.

So the TTL is the **semantic bridge** between that BAS/BMS schema (see `examples/rtu7_snip.png`) and open-fdd’s rule inputs.

## Brick TTL structure

```turtle
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix : <http://openfdd.local/ahu7#> .

:ahu_7 a brick:Air_Handling_Unit ;
    rdfs:label "AHU 7" .

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
- **`ofdd:mapsToRuleInput`** — Rule input name used in YAML (e.g. `oat`, `sat`, `economizer_sig`).

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

## brick_resolver.py — SPARQL queries

`examples/brick_resolver.py` loads the TTL and builds `{rule_input: csv_column}` using a SPARQL query:

```python
from pathlib import Path
from typing import Dict

def resolve_from_ttl(ttl_path: str | Path) -> Dict[str, str]:
    """Load Brick TTL, return {rule_input: csv_column}."""
    from rdflib import Graph

    g = Graph()
    g.parse(ttl_path, format="turtle")
    mapping: Dict[str, str] = {}

    q = """
    PREFIX ofdd: <http://openfdd.local/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?rule_input ?label WHERE {
        ?point ofdd:mapsToRuleInput ?rule_input .
        ?point rdfs:label ?label .
    }
    """
    for row in g.query(q):
        rule_input = str(row.rule_input).strip('"')
        label = str(row.label).strip('"')
        mapping[rule_input] = label

    return mapping
```

**What it does:** Finds every point with `ofdd:mapsToRuleInput` and `rdfs:label`, and returns a dict like `{"oat": "OAT (°F)", "sat": "SAT (°F)", ...}`.

## Using the resolver in your script

```python
import pandas as pd
from pathlib import Path

import open_fdd
from open_fdd import RuleRunner

script_dir = Path(__file__).parent
ttl_path = script_dir / "ahu7_brick_model.ttl"
csv_path = script_dir / "ahu7_sample.csv"

df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

# Resolve from Brick (requires: pip install open-fdd[brick])
import sys
sys.path.insert(0, str(script_dir))
from brick_resolver import resolve_from_ttl

column_map = resolve_from_ttl(ttl_path)
# {"oat": "OAT (°F)", "sat": "SAT (°F)", "economizer_sig": "OA Damper Cmd (%)", ...}

rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,   # Brick-derived mapping
)
```

## Manual vs Brick mapping

You can use either:

| Approach | When |
|----------|------|
| **Manual** | Small script, known columns: `column_map = {"oat": "OAT (°F)", "sat": "SAT (°F)"}` |
| **Brick** | BAS/BMS with a Brick TTL: `column_map = resolve_from_ttl("model.ttl")` |

`RuleRunner.run(column_map=...)` accepts any `{rule_input: df_column}` dict.
