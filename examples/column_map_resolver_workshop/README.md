# Column map resolver workshop

Small examples for **PyPI / engine-only** integrators: build a **`column_map`** from JSON or YAML, then run **`RuleRunner`** on a pandas `DataFrame`.

## Files

| File | Purpose |
|------|---------|
| `manifest_minimal.yaml` | Minimal `column_map` for `demo_one_shot.py` |
| `manifest_brick.yaml` | Brick-style keys |
| `manifest_haystack.yaml` | Illustrative Haystack-derived key names |
| `manifest_dbo.yaml` | Illustrative DBO / Google Digital Buildings–style keys |
| `manifest_223p.yaml` | Illustrative 223P-scoped keys |
| `demo_rule.yaml` | One expression rule (supply air vs threshold) |
| `demo_one_shot.py` | **Manifest + RuleRunner** end-to-end |
| `demo_multi_ontology_illustration.py` | Comments + static dicts showing how each ontology **could** feed the same column |

## Run

From the **open-fdd repo root** with `pip install -e .` or `pip install open-fdd`:

```bash
python examples/column_map_resolver_workshop/demo_one_shot.py
python examples/column_map_resolver_workshop/demo_multi_ontology_illustration.py
```

## API (library)

- `load_column_map_manifest(path)` — load dict from `.json` / `.yaml`
- `ManifestColumnMapResolver(path)` — implements `ColumnMapResolver` for `run_fdd_loop(..., column_map_resolver=...)`
- `FirstWinsCompositeResolver(brick, manifest, ...)` — **first resolver wins per key** (Brick TTL then manifest gap-fill)

See [Engine-only deployment and external IoT pipelines](../../docs/howto/engine_only_iot.md) and `open_fdd/engine/column_map_resolver.py`.

**Security:** We intentionally do **not** load resolver implementations from config strings (avoids import injection). Compose resolvers in Python.
