# Engine pandas FDD — reference

## Public exports (`open_fdd.engine`)

| Symbol | Role |
|--------|------|
| `RuleRunner` | Load rules from path; `run(df, column_map=...)` |
| `load_rule` | Parse one YAML rule file |
| `bounds_map_from_rule` | Extract bounds metadata for plotting |
| `ColumnMapResolver`, `ManifestColumnMapResolver`, `FirstWinsCompositeResolver` | Pluggable column resolution |
| `load_column_map_manifest` | Load manifest JSON/YAML |

Checks (`check_bounds`, `check_expression`, …) live in `open_fdd.engine.checks`; import explicitly if needed.

## Source layout (retained in repo)

| Path | Purpose |
|------|---------|
| `open_fdd/engine/runner.py` | `RuleRunner`, rule loading |
| `open_fdd/engine/checks.py` | Check implementations |
| `open_fdd/engine/column_map_resolver.py` | Resolver types |
| `open_fdd/engine/rule_schema.py` | YAML coercion |
| `open_fdd/schema/` | Pydantic result models |
| `open_fdd/tests/engine/` | Engine tests |
| `examples/` | Runnable rule examples |

## PyPI

- Primary package: `open-fdd` → `import open_fdd.engine`.
- Optional shim: `packages/openfdd-engine` → `import openfdd_engine`.
