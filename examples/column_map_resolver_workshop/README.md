# Column map workshop (minimal)

One rule YAML + one Python script showing how the **same** expression rule can resolve to your DataFrame columns using **Brick**, **Haystack**, **DBO**, or **223P**-style keys in `column_map`.

The rule matches the cookbook pattern ([Expression rule cookbook — How inputs work](../../docs/expression_rule_cookbook.md#how-inputs-work)).

## Run

From the **open-fdd** repo root (`pip install -e .` or `pip install open-fdd`):

```bash
python examples/column_map_resolver_workshop/simple_ontology_demo.py
```

## Files

| File | Purpose |
|------|---------|
| **`simple_ontology_rule.yaml`** | One `type: expression` rule; `inputs` lists `brick`, `haystack`, `dbo`, `s223`, `223p` |
| **`simple_ontology_demo.py`** | Builds a tiny DataFrame, runs the rule five times with a different `column_map` key each time, prints whether the fault flag fired |

## Library helpers (optional)

For YAML manifests on disk, use `load_column_map_manifest` or `ManifestColumnMapResolver` from `open_fdd.engine.column_map_resolver`. See [Column map & resolvers](../../docs/column_map_resolvers.md).
