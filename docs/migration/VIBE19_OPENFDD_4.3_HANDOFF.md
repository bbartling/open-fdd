# Vibe19 integration handoff (open-fdd 4.3.0)

Vibe19 application code is **not** in this repository. Consume the PyPI package.

## Constraint

```
open-fdd>=4.3.0,<5
```

## Extras

```
pip install "open-fdd[reporting]"
# or: pip install "open-fdd[oracle]" / "open-fdd[analytics]"
# not: open-fdd[vibe19]  (deprecated alias through 4.3; gone in 5.0)
```

## APIs

| Need | Import |
| --- | --- |
| Version / hashes | `open_fdd.manifest()` / `open_fdd.version.manifest()` |
| Effective catalog | `open_fdd.catalog.effective_catalog`, `rule_catalog_hash`, `effective_config_hash` |
| Run rules | `open_fdd.rules.run_rule`, `run_all` |
| Quality | `open_fdd.quality.assess_frame`, `normalize_role_series` |
| Evidence | `RuleResult.to_dict()` → JSON-safe metrics + `evidence` |
| Occupancy | `open_fdd.analytics.OccupancySchedule`, `occupied_mask` |
| Metering | `open_fdd.analytics.build_meter_monthly_table` |
| RCx ranking | `open_fdd.analytics.zone_comfort_fail_ranking` |

## Schemas

- Catalog JSON: `schema_version` = `open-fdd-catalog-v1`
- Inventory: `sql_rules/generated/parity_inventory.yaml` `parity-inventory-v2`
- Result statuses: `PASS`, `FAULT`, `SKIPPED_MISSING_ROLES`, `SKIPPED_EQUIPMENT_OFF`, `NOT_APPLICABLE_EQUIPMENT_TYPE`, `ERROR`

## Semantic notes for existing dashboards

- CHW-1 idle plants will **skip** instead of showing huge fault hours.
- SCHED-247 pressure-only sites will **PASS** this ID; use `inferred_runtime_hours` in metrics.
- Persist `rule_catalog_hash` + `effective_config_hash` next to findings.

## Tests consumers should run

```
python -c "from open_fdd import manifest; assert manifest()['open_fdd_python_version'] >= '4.3.0'"
```
