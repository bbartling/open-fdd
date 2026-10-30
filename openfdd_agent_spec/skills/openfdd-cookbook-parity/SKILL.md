---
name: openfdd-cookbook-parity
description: >-
  Use when editing rule cookbooks, parity matrix, or cookbook CI
  (cookbook-parity.yml, cookbook_parity_check.py). Triggers on: pandas cookbook,
  SQL cookbook, parity-matrix, gap-matrix, rule headings.
---

# Cookbook parity

See [`docs/COOKBOOK_OWNERSHIP.md`](../../docs/COOKBOOK_OWNERSHIP.md).

```bash
python scripts/cookbook_parity_check.py --all
# or --docs-only in lighter CI jobs
```

Workflow: `.github/workflows/cookbook-parity.yml`.

SI (`metric-c-v2`) is canonical for storage and processing. Engineer-declared source units are normalized once by the Timescale writer; rule parameters declare semantic kinds and SI units. Display preference conversion is presentation-only.

When changing rule identity or count, update both cookbooks and the parity matrix in the same PR family. Preserve the PostgreSQL SQL expression cookbook and pandas oracle cookbook. Accidental cookbook shrinkage must fail CI.

For SI cutover claims, document the ordered chain: frozen IP baseline, pandas IP = pandas SI, pandas SI = SQL SI, then live post-cutover SQL SI = IP baseline per site. Offline parity does not establish live P3 or FQ.

Display-name contract (registry `description` ↔ cookbook short title ↔ React
labels): [`docs/RULE_DISPLAY_NAMES.md`](../../docs/RULE_DISPLAY_NAMES.md).

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-sql-fdd`](../openfdd-sql-fdd/SKILL.md) — Timescale SQL expression
- [`openfdd-pypi-oracle`](../openfdd-pypi-oracle/SKILL.md) — pandas package
- [`openfdd-architecture`](../openfdd-architecture/SKILL.md) — what stays out of central
