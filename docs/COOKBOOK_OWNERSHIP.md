# Cookbook ownership

Both expression cookbooks are **permanent project deliverables**.

| Cookbook | Path | Engine |
| --- | --- | --- |
| DataFusion SQL | [`docs/rules/cookbook/datafusion-sql-cookbook.md`](rules/cookbook/datafusion-sql-cookbook.md) | Production (`sql_rules/`) |
| Pandas | [`docs/rules/cookbook/pandas-cookbook.md`](rules/cookbook/pandas-cookbook.md) | Oracle (`open_fdd.rules` on PyPI) |
| Parity matrix | [`docs/rules/cookbook/parity-matrix.md`](rules/cookbook/parity-matrix.md) | Honesty layer |
| Parity inventory | [`sql_rules/generated/parity_inventory.yaml`](../sql_rules/generated/parity_inventory.yaml) | Machine-readable Wave 0+ contract |

Product UI is **React** (`frontend/web` → `openfdd-web`). Product FDD execution is **Rust/DataFusion**. Pandas is the **PyPI reference/oracle** only — never a central/web request-path dependency.

Catalog arithmetic: **62** pandas diagnostic concepts + **4** SQL analytics (`FAN-RUNTIME-HOURS`, `AVG-ZONE-TEMP`, `ZONE-COMFORT-PCT`, `FAULT-ELAPSED-HOURS`) = **66** SQL registry entries. `FC13-SAT-HIGH` is the SQL canonical id (`FC13` alias). `SV-SLEW` aliases `SV-RATE`.

## Rules for agents

1. Never delete either cookbook because the other engine is “canonical for production.”
2. Never replace cookbooks with generated API documentation alone.
3. Keep rule IDs and metadata synchronized; be honest about parity gaps.
4. Hand-written engineering expressions stay in cookbooks — manifests hold identity/metadata only.
5. CI: `.github/workflows/cookbook-parity.yml` → `scripts/parity_inventory_check.py`, `scripts/sql_pandas_oracle_check.py`, `scripts/cookbook_parity_check.py`, `scripts/rule_parity_mutation_check.py`.
6. When adding a production SQL rule, update registry + SQL file + cookbook heading + parity inventory + fixture scaffold.
7. When adding a pandas oracle rule, update `open_fdd.rules` + pandas cookbook + inventory.

## Parity levels (Wave 0+)

`concept_only` → `sql_screening` → `predicate_parity` → `mask_parity` → `duration_parity` → `site_soak`

Do not use legacy labels `proven_building_100` / `ported_from_cookbook`. Claims above `sql_screening` require executable pandas↔DataFusion fixtures.

## Spec twin

Agent-spec copy (same rules): [`../openfdd_agent_spec/docs/COOKBOOK_OWNERSHIP.md`](../openfdd_agent_spec/docs/COOKBOOK_OWNERSHIP.md).
