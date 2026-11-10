---
title: Development
nav_order: 17
---

# Development

Develop and test on a workstation. The NF mock serves the Full app locally:

```bash
node nf-app/dev/mock-nf.mjs
```

Open the app through the mock's local app route. It uses deterministic synthetic model and history data and performs
no field-device writes.

## Check generated FDD files

```bash
python3 scripts/nf/build_rule_catalog.py --check
python3 scripts/nf/build_sql_pack.py --check
python3 scripts/nf/gen_rule_docs.py --check
python3 scripts/nf/gen_cookbook.py --check
```

Run the Node tests with `node --test` against the test files in nf-app/tests and lite/tests. Run the pandas/SQL parity
suite with `python -m pytest tests/parity -q`. Use the
[SQL rules guide](sql-rules.html) and [pandas rules guide](pandas-rules.html) for rule-specific workflows.

The repository also contains the Lite app, NF installer, Timescale schema, RDF checker, and Python package. Start with
AGENTS.md and openfdd_agent_spec/README.md for contributor rules and architecture.
