---
name: add-or-tune-fdd-rule
description: Add or tune an FDD rule in sql/fdd and rebuild the catalog, SQL packs and rule docs.
---
# Add or tune an FDD rule

1. Edit the rule SQL in `sql/fdd/postgres/rules/` and its entry in `sql/fdd/registry.yaml` (roles, parameters with
   SI units and defaults, `confirm_seconds`). New roles: `sql/fdd/role_map.json`; NF-class overrides:
   `nf-app/rules/role_overrides.json`. Thresholds are SI; never convert in SQL.
2. Rebuild (generated files, never hand-edit):
   `python3 scripts/nf/build_rule_catalog.py` then `python3 scripts/nf/build_sql_pack.py` then
   `python3 scripts/nf/gen_rule_docs.py`.
3. Engine parity: `node --test nf-app/tests/engines.test.mjs` (the SQLite pack must equal Postgres on every rule).
4. pandas parity: if the rule has a pandas twin in `open_fdd/rules`, keep it equal; the harness is `tests/parity/`
   (workflow `.github/workflows/parity.yml`, pandas oracle vs SQL pack).
5. Full check: `node --test nf-app/tests/*.test.mjs`, then `python3 scripts/nf/build_rule_catalog.py --check`,
   `python3 scripts/nf/build_sql_pack.py --check` and `python3 scripts/nf/gen_rule_docs.py --check`.

Do not add name, suffix or key-syntax matching to find points; roles bind by NF class, else Haystack markers
(`DATA_CONTRACT.md`). Do not edit `sql/fdd` while another change to it is in flight.
