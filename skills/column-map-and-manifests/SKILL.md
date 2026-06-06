---
name: column-map-and-manifests
description: "Maps BRICK/ontology input keys to historian columns via model JSON or manifests. Use when Arrow Rule Lab rules reference logical point names (brick_type, fdd_input) that must bind to feather column headers per site."
---

# Column map and manifests

## When to use / When not to use

Use when Arrow rules (`table["SAT"]` or cookbook helpers) reference logical inputs (e.g. `SAT`, `OAT`) that must bind to historian column names per site.

Skip when every rule already uses raw column names matching the feather store.

## Prerequisites

- `open-fdd` installed.
- Optional: site `model.json` or manifest JSON if mimicking desktop BRICK workflows (rdflib not required for dict/manifest maps).

## Quick start

```python
from open_fdd.arrow_runtime import build_column_map_from_model_points
import json

model = json.loads(Path("workspace/data/model.json").read_text())
column_map = build_column_map_from_model_points(model, site_id="demo")
# column_map["SAT"] → feather column header for supply air temp
```

## Core concepts

- **Dict map:** plain `column_map` passed to `run()`.
- **Manifest:** JSON listing site → input key → column.
- **Composite:** `FirstWinsCompositeResolver` chains resolvers.

## Compose with other skills

- [engine-pandas-fdd](../engine-pandas-fdd/SKILL.md)
- [brick-ttl-data-model](../brick-ttl-data-model/SKILL.md) when TTL/model drives maps

## Verification

```bash
pytest open_fdd/tests/engine/test_column_map_from_model.py -q
```

## Gotchas

- Brick/rdf-based resolvers were desktop-only; generated apps should use dict/manifest unless operator adds rdflib.

See [references/REFERENCE.md](references/REFERENCE.md).
