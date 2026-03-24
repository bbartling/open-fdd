# openfdd-engine

Standalone Pandas/YAML FDD engine extracted from Open-FDD.

## Install

```bash
pip install openfdd-engine
```

For Brick TTL mapping support:

```bash
pip install "openfdd-engine[brick]"
```

## API

- `RuleRunner`
- `load_rule()`
- `bounds_map_from_rule()`
- `resolve_from_ttl()`

Rule authoring guidance remains in the Open-FDD docs:
- `docs/expression_rule_cookbook.md`

