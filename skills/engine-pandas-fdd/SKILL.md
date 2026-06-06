---
name: engine-pandas-fdd
description: "RETIRED 3.0.1 — YAML/pandas RuleRunner removed from PyPI. Use Arrow Rule Lab and rules-crud-and-batch-run instead."
---

# RETIRED — engine-pandas-fdd

**Removed in open-fdd 3.0.1.** The YAML `RuleRunner` / pandas engine is no longer shipped on PyPI.

Use instead:

- **Operator FDD:** [skills/rules-crud-and-batch-run/SKILL.md](../rules-crud-and-batch-run/SKILL.md) — `apply_faults_arrow` in Rule Lab
- **Offline lint:** `open_fdd.arrow_runtime.run_arrow_rule`
- **Graph ML (future):** [skills/ml-lab-sklearn/SKILL.md](../ml-lab-sklearn/SKILL.md) · [issue #211](https://github.com/bbartling/open-fdd/issues/211)

Legacy source remains under `open_fdd/engine/` in the repo for reference only — not included in the wheel.
