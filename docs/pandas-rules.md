---
title: Writing pandas rules
nav_order: 6
---

# Write a pandas rule

`open_fdd.rules` provides reference implementations for offline analysis and notebooks. The NF app runs the generated
SQL pack. Pandas and SQL should report the same result for the same SI input unless a difference is explicitly
documented and tested.

## Rule inputs and result

Each rule receives a pandas `DataFrame` with a UTC `DatetimeIndex`, one column per Haystack role, and SI values.
Metadata such as role units and equipment kind travels in `DataFrame.attrs`. A rule returns a `RuleResult` with status,
fault hours, coverage, and diagnostic notes. Missing roles, unknown values, and zero assessed coverage remain
not-assessed. Do not report them as healthy.

## Add or change a rule

1. Add the function and rule metadata in `open_fdd/rules/` and register it in `cookbook_catalog.py`.
2. Keep role names, units, defaults, confirmation rules, and operational gating aligned with the SQL registry.
3. Add a deterministic pandas test for fault, healthy, missing-input, and boundary behavior.
4. Add or update the same case in the SQL parity fixture. The harness compares fault hours by equipment and checks
   SQL pack behavior across engines.
5. If the algorithms intentionally differ, add a reason to `KNOWN_DIVERGENT` in `tests/parity/test_parity.py` and
   document the scope in `sql/fdd/KNOWN_DIFFERENCES.md`.
6. Regenerate the cookbook and check generated files.

## Run the parity checks

```bash
python -m pytest tests/parity -q
python scripts/nf/gen_cookbook.py
python scripts/nf/gen_cookbook.py --check
```

Parity runs a deterministic synthetic dataset through pandas, PostgreSQL SQL in PGlite, and SQLite. A passing case
means the declared outputs agree on that dataset within the harness tolerance. It does not prove agreement for every possible
input. Read the generated [parity report](rules/parity.html) before comparing a documented divergence. The
[pandas cookbook](rules/pandas-cookbook.html) shows each registered function and a runnable example.

Use [Writing SQL rules](sql-rules.html) for the production query contract and [Units](units.html) for the SI rules.
