---
title: PyPI agent tools
layout: default
nav_order: 11
has_children: true
permalink: /ecm/
---

# PyPI agent tools — RCx/FDD reports and ECM workbooks

`pip install open-fdd` is the agent library: an RCx/FDD PDF from mapped roles, plus human-auditable Excel ECM workbooks. **Not** the product DataFusion FDD runtime (that is GHCR central). The PDF is not Railway-only. `open-fdd-anomaly report` reads a local CSV plus column map. The same template accepts a Railway or self-hosted Open-FDD history frame, or a future vendor API, once those rows are mapped to roles.

Any AI agent that can read markdown skills and run the CLI can use this. Skills live in `openfdd_agent_spec/skills/`. Sync with `./scripts/openfdd_install_agent_skills.sh --sync`.

```bash
pip install "open-fdd[anomaly]" "open-fdd[reporting]"
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --compile
pip install open-fdd                 # ECM engineering + Excel workbooks
```

## Community review — help wanted

We welcome technical review of workbook formulas, Python referee calculators, and M&V helpers. **[GitHub issue #985](https://github.com/bbartling/open-fdd/issues/985)** tracks feedback (`help wanted` / `good first issue`) and **remains open** as a standing invitation — even as docs improve.

- **Scope:** [Engineering calcs](engineering-calcs.html) (full module catalog), [Install & overview](overview.html) (minimal PyPI check commands), [IPMVP change-point & G14](ipmvp-changepoint.html).
- **Quick check:** `pip install open-fdd` → `open-fdd-ecm demo --out ./Demo_ECMs.xlsx` → review one sheet you know.
- **Feedback:** comment on [#985](https://github.com/bbartling/open-fdd/issues/985), or open a PR with fixes/tests. No confidential site data in public threads.

## Start here

1. [Purpose: Excel + EnergyPlus](purpose-excel-energyplus.html) — workflow story  
2. [**Engineering calcs**](engineering-calcs.html) — **all** modules + calculators + finance/EUI  
3. [Install & API overview](overview.html) — `ECMJob`, CLI  
4. [**AI agents & skills**](agent-context.html) — what agents do + skill links  
5. [**IPMVP change-point & G14**](ipmvp-changepoint.html) — Option C baselines + Guideline 14 scores (pandas oracle)
6. [**Model → ECM calculations**](model-to-calculations.html) — EQ-VOCAB → calculator adapter (ECM-ADAPT)

**Boundary:** [Compute boundary ownership](../architecture/compute_boundary_ownership.html) — PyPI/ECM is external tooling, not central/web images.
