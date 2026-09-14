---
title: PyPI agent tools
layout: default
nav_order: 11
has_children: true
permalink: /ecm/
---

# PyPI agent tools — ECM engineering for AI agents

This section is for **energy / RCx engineers and AI agents** who need a **human-auditable Excel workbook** of industry-method ECM calcs — and an honest **compare against EnergyPlus** modeling. It is **not** the Open-FDD product FDD runtime (that is **DataFusion SQL on GHCR**).

```bash
pip install open-fdd                 # ECM engineering + Excel workbooks
pip install "open-fdd[oracle]"       # + pandas rules / analytics
```

## What this is for

| Need | What the wheel does |
|------|---------------------|
| **Engineering calcs** | Industry-method screens (fan affinity, boiler reset, SAT/DAT, schedules, …) as **live Excel formulas** an engineer can open and audit |
| **AI → Excel** | An agent fills **input cells only** via `ECMJob` — never invents formula cells; workbook stays the human calculation record |
| **EnergyPlus compare** | Attach twin / cascade results → honesty sheets (`Industry_Screening`, `Measures`, FITTED / BALLPARK / NO_EP) so the sheet is a **second set of eyes** on the model — not a rubber stamp |

**Talk track:** we do not fit the spreadsheet to EnergyPlus. We check the model against the same methods ESCO books use, and we label honesty status so buyers are not greenwashed.

## Start here

1. [Purpose: Excel + EnergyPlus](purpose-excel-energyplus.html) — workflow story (agent → xlsx → twin compare)
2. [Engineering calcs](../operations/ECM_ENGINEERING_MATH.html) — formulas agents put into workbooks
3. [Install & API overview](overview.html) — `pip` extras, `ECMJob`, CLI
4. [Agent rules](AGENTS_ECM_ENGINEERING.html) — provenance, no invented inputs
5. [Golden handoff](OPENFDD_AGENT_ECM_HANDOFF.html) — Liberty dual-AHU parity workbook
6. [Upsell brief](ENGINEER_UPSELL_BRIEF.html) — sales / freeze pitch
7. [PyPI release checklist](PYPI_RELEASE_CHECKLIST.html) — when math changes

**Boundary:** [Compute boundary ownership](../architecture/compute_boundary_ownership.html) — PyPI/ECM is external tooling, not central/web images.

> **Wave O O11:** more pages may land while the human inspects docs — section stays open until backlog is empty.
