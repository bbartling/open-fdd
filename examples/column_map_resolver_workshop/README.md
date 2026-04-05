# Column map resolver workshop

Small examples for **PyPI / engine-only** use: load a **`column_map`** from YAML, run **`RuleRunner`** on a pandas **`DataFrame`**.

## Run one ontology in one command

From the **open-fdd repo root** (with `pip install -e .` or `pip install open-fdd`):

```bash
# List modes
python examples/column_map_resolver_workshop/run_ontology_demo.py --list

# Brick-style keys (same rule as minimal, manifest includes oat)
python examples/column_map_resolver_workshop/run_ontology_demo.py brick

# Minimal Brick key set (supply air only in manifest)
python examples/column_map_resolver_workshop/run_ontology_demo.py minimal

# Haystack-style slugs → columns sat / oat
python examples/column_map_resolver_workshop/run_ontology_demo.py haystack

# DBO / Google Digital Buildings–style type names
python examples/column_map_resolver_workshop/run_ontology_demo.py dbo

# 223P-style scoped slugs (Python-safe names for expression rules)
python examples/column_map_resolver_workshop/run_ontology_demo.py 223p
```

Each mode loads a **`manifest_*.yaml`** + matching **`demo_rule*.yaml`**, builds the same sample **`DataFrame`** (`sat` hits 105 °F once), and prints rows plus whether **`demo_high_sat_flag`** fired.

## Files

| File | Purpose |
|------|---------|
| **`run_ontology_demo.py`** | CLI: **`brick`**, **`minimal`**, **`haystack`**, **`dbo`**, **`223p`** |
| `manifest_minimal.yaml` | One Brick-class key → `sat` (runs with `demo_rule.yaml`) |
| `manifest_brick.yaml` | Brick keys for SA + OA temps |
| `manifest_haystack.yaml` | Haystack-style slugs → `sat` / `oat` |
| `manifest_dbo.yaml` | DBO-style type names → `sat` / `oat` |
| `manifest_223p.yaml` | Illustrative **slash** labels (not for `expression` rules) |
| `manifest_223p_safe.yaml` | 223P-style **safe** slugs → use with `demo_rule_223p.yaml` |
| `demo_rule.yaml` | Expression rule (Brick input name) |
| `demo_rule_haystack.yaml` | Same check, Haystack input name |
| `demo_rule_dbo.yaml` | Same check, DBO input name |
| `demo_rule_223p.yaml` | Same check, 223P safe slug |
| `demo_one_shot.py` | Original minimal manifest + `demo_rule` (no CLI) |
| `demo_multi_ontology_illustration.py` | Prints static dicts + loads every `manifest_*.yaml` |

## API (library)

- `load_column_map_manifest(path)` — load dict from `.json` / `.yaml`
- `ManifestColumnMapResolver(path)` — `ColumnMapResolver` for custom pipelines
- `FirstWinsCompositeResolver(...)` — first resolver wins per key (e.g. Brick TTL + manifest gap-fill)

See **[Engine-only & IoT](../../docs/howto/engine_only_iot.md)** on this repo’s docs site and `open_fdd/engine/column_map_resolver.py`.

**Security:** Resolver classes are **not** loaded from config strings (avoids import injection). Compose resolvers in Python.
