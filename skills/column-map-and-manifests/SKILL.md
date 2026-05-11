---
name: column-map-and-manifests
description: "Maps BRICK/ontology input keys to pandas columns using dicts, manifests, or composite resolvers in open_fdd.engine. Use when integrating site-specific point names with YAML FDD rules."
---

# Column map and manifests

## When to use / When not to use

Use when rule YAML references logical inputs (e.g. `SAT`, `OAT`) that must bind to DataFrame columns per site.

Skip when every rule already uses raw column names matching the DataFrame.

## Prerequisites

- `open-fdd` installed.
- Optional: site `model.json` or manifest JSON if mimicking desktop BRICK workflows (rdflib not required for dict/manifest maps).

## Quick start

```python
from open_fdd.engine import RuleRunner, ManifestColumnMapResolver, load_column_map_manifest

manifest = load_column_map_manifest("column_map.json")
resolver = ManifestColumnMapResolver(manifest)
column_map = resolver.resolve_for_site("site-01")
runner = RuleRunner(rules_path="rules")
out = runner.run(df, column_map=column_map)
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
