---
title: Purpose — Excel + EnergyPlus
parent: PyPI agent tools
nav_order: 1
permalink: /ecm/purpose-excel-energyplus.html
---

# Purpose: engineering calcs in Excel, checked against EnergyPlus

Open-FDD’s **PyPI** package (`open-fdd`) exists so an **AI agent** (or engineer script) can:

1. Run **industry-method ECM screens** in Python (benchmark referee).
2. Write those inputs into a **real Excel workbook** with **live formulas** the engineer reviews.
3. Optionally attach **EnergyPlus / twin cascade** results and export **honesty** sheets — so the workbook compares spreadsheet savings to modeled kWh without pretending they are the same thing.

This is **ECM / ROI engineering tooling**. Product **fault detection** stays on the [GHCR stack]({{ site.baseurl }}/quick-start/docker-ghcr.html) (DataFusion SQL). Do not treat the wheel as the FDD runtime.

---

## Why Excel (not only Python)

| Role | Owner |
|------|--------|
| **Input cells** | Agent or engineer fills rates, fan kW, hours, speeds, efficiencies from BAS / meters / TAB / nameplates |
| **Formula cells** | Stay in the workbook — agent **must not** overwrite them |
| **Python `job.calc(...)`** | Independent benchmark — a referee, not hidden sheet math |
| **Human review** | Engineer opens the `.xlsx`, challenges assumptions, signs off |

If the only artifact is a JSON blob, the customer cannot audit the calc. The workbook **is** the calculation record.

---

## Agent → Excel (happy path)

```python
from open_fdd.ecm_engineering import ECMJob

job = (
    ECMJob("Lincoln Middle School")
    .set_global(area_ft2=85000, electric_rate=0.145, gas_rate=0.92)
    .add_ecm(
        "static_pressure_reset",
        fan_kw=55.9,
        hours=4100,
        baseline_speed=0.82,
        proposed_speed=0.67,
    )
    .add_ecm(
        "boiler_reset",
        base_therms=48000,
        base_eff=0.86,
        prop_eff=0.92,
    )
)

path = job.save("Lincoln_Middle_School_ECMs.xlsx")
```

What the agent did:

- Created a project workbook from the packaged template.
- Wrote **global** and **ECM module inputs** only.
- Left Excel formulas intact for savings / payback screens.

See [Install & API overview](overview.html) and [Agent rules](AGENTS_ECM_ENGINEERING.html). Calcs behind the screens: [Engineering calcs]({{ site.baseurl }}/operations/ECM_ENGINEERING_MATH.html).

---

## EnergyPlus / twin compare (second set of eyes)

When a twin or EnergyPlus cascade is available, attach it before save:

```python
job.attach_twin_compare(cascade_payload)  # or .export_honesty(True)
job.save("Lincoln_Middle_School_ECMs.xlsx")
```

Honesty export adds sheets such as **Contents**, **Model_Provenance**, **Inputs**, **Industry_Screening**, and **Measures**. Status labels (product contract):

| Status | Meaning |
|--------|---------|
| **FITTED** | Hours / inputs were reverse-fitted to match E+ — exact match is **not** independent proof |
| **BALLPARK** | Independent industry screen vs E+ within an honesty band |
| **NO_EP** | No EnergyPlus / patch for this measure — **do not invent** `ep_kwh` |
| **FAIL_SIGN** | Spreadsheet and model disagree in sign (e.g. sheet saves, model worsens) |

**Rule:** never greenwash a fitted FLH match as BALLPARK. Never invent E+ kWh when the patch is missing.

Sales pitch and proof points: [Engineer upsell brief](ENGINEER_UPSELL_BRIEF.html).  
Golden dual-AHU workbook: [Agent handoff](OPENFDD_AGENT_ECM_HANDOFF.html).  
Bug register (sheet ↔ E+): [BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS]({{ site.baseurl }}/migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.html) (if published) or in-repo `docs/migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md`.

---

## What this is *not*

- Not investment-grade IPMVP M&V by itself.
- Not a substitute for fixing a bad IDF patch (see SAT reset / dual-AHU lessons in the upsell brief).
- Not the Open-FDD React / central FDD product path.

---

## Next pages

| Page | Use when |
|------|----------|
| [Engineering calcs]({{ site.baseurl }}/operations/ECM_ENGINEERING_MATH.html) | You need the math agents encode into Excel |
| [Install & overview](overview.html) | `pip` extras, CLI, module vs calculator names |
| [Agent rules](AGENTS_ECM_ENGINEERING.html) | Guardrails before letting an agent touch a job |
| [PyPI release checklist](PYPI_RELEASE_CHECKLIST.html) | Calcs or templates changed — republish the wheel |
