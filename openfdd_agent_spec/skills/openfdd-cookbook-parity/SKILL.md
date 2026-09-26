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

When changing rule identity or count, update both cookbooks and the parity
matrix in the same PR family. Accidental cookbook shrinkage must fail CI
(harden under Milestone A Phase 0/2).

Display-name contract (registry `description` ↔ cookbook short title ↔ React
labels): [`docs/RULE_DISPLAY_NAMES.md`](../../docs/RULE_DISPLAY_NAMES.md).

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-sql-fdd`](../openfdd-sql-fdd/SKILL.md) — DataFusion expression
- [`openfdd-pypi-oracle`](../openfdd-pypi-oracle/SKILL.md) — pandas package
- [`openfdd-architecture`](../openfdd-architecture/SKILL.md) — what stays out of central
