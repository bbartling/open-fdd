# Cookbook ownership

Both expression cookbooks are **permanent project deliverables**. SI (`metric-c-v2`) is the storage and processing ABI; no engine or cookbook is a second telemetry writer.

| Cookbook | Path | Engine |
| --- | --- | --- |
| PostgreSQL / Timescale SQL | [`docs/rules/cookbook/sql-cookbook.md`](../../docs/rules/cookbook/sql-cookbook.md) | Production expression catalog and SQL reference (`sql/fdd/` on Timescale) |
| Pandas | [`docs/rules/cookbook/pandas-cookbook.md`](../../docs/rules/cookbook/pandas-cookbook.md) | Oracle (`open_fdd.rules`) |
| Parity matrix | [`docs/rules/cookbook/parity-matrix.md`](../../docs/rules/cookbook/parity-matrix.md) | Honesty layer |
| Gap / taxonomy / schema | sibling files under `docs/rules/cookbook/` | Supporting |

## Unit and parity contract

SI (`metric-c-v2`) is canonical for rule and analytics processing. Each source point has an engineer-declared unit and quantity; the single Timescale writer normalizes supported inputs once. Parameter metadata declares a semantic `kind` and SI unit. The parity chain is frozen IP baseline → pandas IP = pandas SI → pandas SI = SQL SI → live post-cutover SQL SI = IP baseline (P3). `displayIP` is allowed as a user presentation preference; it does not alter storage or computation. FQ remains unclaimed until live P3 and live P2 pass for every site. See [units](../../docs/modeling/units.md) and [ADR-012](../../docs/architecture/adr-012-si-processing-and-qualification.md).

## Rules for agents

1. Never delete either cookbook because the other engine is “canonical for production.”
2. Never replace cookbooks with generated API documentation alone.
3. Keep rule IDs and metadata synchronized; be honest about parity gaps.
4. Hand-written engineering expressions stay in cookbooks — manifests hold identity/metadata only.
5. CI: `.github/workflows/cookbook-parity.yml` → inventory + `sql_pandas_oracle_check.py` + `cookbook_parity_check.py`.
8. When adding a production SQL rule, update registry + SQL file + cookbook heading + inventory + fixture scaffold.
9. When adding a pandas oracle rule, update `open_fdd.rules` + pandas cookbook + inventory.
10. **Display names:** registry `description` = short UI name; cookbook heading must match — see [`RULE_DISPLAY_NAMES.md`](../../openfdd_agent_spec/docs/RULE_DISPLAY_NAMES.md).
11. Canonical doc also at [`docs/COOKBOOK_OWNERSHIP.md`](../../docs/COOKBOOK_OWNERSHIP.md).

## Milestone A hardening targets

Detect: missing headings, duplicate IDs, missing SQL files, missing pandas entries,
undocumented SQL-only rules, broken aliases, parameter/role drift, accidental
shrinkage, broken links, examples that no longer import.
