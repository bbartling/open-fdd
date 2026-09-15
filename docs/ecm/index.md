---
title: PyPI agent tools
layout: default
nav_order: 11
has_children: true
permalink: /ecm/
---

# PyPI agent tools — ECM engineering for AI agents

Human-auditable Excel ECM workbooks + EnergyPlus honesty via `pip install open-fdd`. **Not** the product DataFusion FDD runtime (that is GHCR central).

```bash
pip install open-fdd                 # ECM engineering + Excel workbooks
pip install "open-fdd[oracle]"       # + pandas rules / analytics
```

## Start here

1. [Purpose: Excel + EnergyPlus](purpose-excel-energyplus.html) — workflow story  
2. [**Engineering calcs**](engineering-calcs.html) — **all** modules + calculators + finance/EUI  
3. [Install & API overview](overview.html) — `ECMJob`, CLI  
4. [**AI agents & skills**](agent-context.html) — what agents do + skill links  

**Boundary:** [Compute boundary ownership](../architecture/compute_boundary_ownership.html) — PyPI/ECM is external tooling, not central/web images.
