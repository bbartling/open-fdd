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
