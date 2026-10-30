# Cookbook ownership

Both expression cookbooks are **permanent project deliverables**. SI (`metric-c-v2`) is the storage and processing ABI; no engine or cookbook is a second telemetry writer.

| Cookbook | Path | Engine |
| --- | --- | --- |
| PostgreSQL / Timescale SQL | [`docs/rules/cookbook/sql-cookbook.md`](rules/cookbook/sql-cookbook.md) | Production expression catalog and SQL reference (`sql/fdd/` on Timescale) |
| Pandas | [`docs/rules/cookbook/pandas-cookbook.md`](rules/cookbook/pandas-cookbook.md) | Oracle (`open_fdd.rules` on PyPI) |
| Parity matrix | [`docs/rules/cookbook/parity-matrix.md`](rules/cookbook/parity-matrix.md) | Honesty layer |
| Parity inventory | [`sql_rules/generated/parity_inventory.yaml`](../sql_rules/generated/parity_inventory.yaml) | Machine-readable Wave 0+ contract |

Product UI is **React** (`frontend/web` → `openfdd-web`). Product FDD execution is **Timescale / PostgreSQL SQL** (`sql/fdd`); DataFusion is prohibited on the active product path. Pandas is the **PyPI reference/oracle** only — never a central/web request-path dependency.

Catalog inventory at this tip: **71** pandas diagnostics and **77** SQL registry entries (71 diagnostics plus six SQL-only/utility rules). These counts describe catalog presence, not parity proof. `FC13-SAT-HIGH` is the SQL canonical id (`FC13` alias). `SV-SLEW` aliases `SV-RATE`.

## Unit and parity contract

SI (`metric-c-v2`) is canonical for rule and analytics processing. Each source point has an engineer-declared unit and quantity; the single Timescale writer normalizes supported inputs once. Parameter metadata declares a semantic `kind` and SI unit. The parity chain is frozen IP baseline → pandas IP = pandas SI → pandas SI = SQL SI → live post-cutover SQL SI = IP baseline (P3). `displayIP` is allowed as a user presentation preference; it does not alter storage or computation. FQ remains unclaimed until live P3 and live P2 pass for every site. See [units](modeling/units.md) and [ADR-012](architecture/adr-012-si-processing-and-qualification.md).

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

Do not use legacy labels `proven_building_100` / `ported_from_cookbook`. Claims above `sql_screening` require executable pandas↔Timescale SQL fixtures.

## Spec twin

Agent-spec copy (same rules): [`../openfdd_agent_spec/docs/COOKBOOK_OWNERSHIP.md`](../openfdd_agent_spec/docs/COOKBOOK_OWNERSHIP.md).
