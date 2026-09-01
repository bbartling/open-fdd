# Cookbook ownership

Both expression cookbooks are **permanent project deliverables**.

| Cookbook | Path | Engine |
| --- | --- | --- |
| DataFusion SQL | [`docs/rules/cookbook/datafusion-sql-cookbook.md`](../../docs/rules/cookbook/datafusion-sql-cookbook.md) | Production (`sql_rules/`) |
| Pandas | [`docs/rules/cookbook/pandas-cookbook.md`](../../docs/rules/cookbook/pandas-cookbook.md) | Oracle (`open_fdd.rules`) |
| Parity matrix | [`docs/rules/cookbook/parity-matrix.md`](../../docs/rules/cookbook/parity-matrix.md) | Honesty layer |
| Gap / taxonomy / schema | sibling files under `docs/rules/cookbook/` | Supporting |

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
