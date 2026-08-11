# open-fdd 4.3.0 — consumer migration

Pin **`open-fdd>=4.3.0,<5`**. Product FDD remains DataFusion on GHCR; this wheel is the pandas oracle.

## Extras

| Install | Use |
| --- | --- |
| `open-fdd[oracle]` | pandas rules |
| `open-fdd[analytics]` | occupancy, metering, RCx, schedule helpers |
| `open-fdd[reporting]` | Engineering Findings |

`open-fdd[vibe19]` still resolves to `reporting` for this minor series and emits `DeprecationWarning` if you `import open_fdd.vibe19`. **Removed in 5.0.**

## Version API

```python
from open_fdd import manifest
doc = manifest()
# open_fdd_python_version, git_revision, rust_engine_version,
# rule_catalog_hash, effective_config_hash, catalog_schema_version
```

CLI: `open-fdd-version --pretty`

Effective catalog (defaults + overrides): `open_fdd.catalog.effective_catalog(overrides_by_rule=...)`.

## Behavior changes

- **CHW-1 / hydronic rules:** missing pump/chiller proof → `SKIPPED_MISSING_ROLES`. Status/amps/power all zero → `SKIPPED_EQUIPMENT_OFF` (no thousands of ΔT hours).
- **SCHED-247:** status/current outrank command. Duct pressure is inferred runtime only and no longer ORs into this rule ID.
- **Quality:** sentinels `999`/`888`/`-999` are invalid; zeros remain valid for status/command.
- **Evidence JSON:** `RuleResult.to_dict()` is compact structured data — never a pandas `...` repr.

## True counts

59 pandas diagnostics. 63 SQL registry entries (those 59 + 4 analytics). Aliases are not extra rules.

## Do not

- Import Streamlit or application UI into Open-FDD.
- Treat matching rule counts as semantic parity. Use golden fixtures + `rule_catalog_hash`.
