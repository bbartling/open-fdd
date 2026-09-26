---
title: Install & ECM overview
parent: PyPI agent tools
nav_order: 3
permalink: /ecm/overview.html
---

# Open-FDD Python package (PyPI)

`open-fdd` (PyPI **4.1+**) ships:

1. **ECM engineering** (`open_fdd.ecm_engineering`) — agent-drivable HVAC spreadsheet workbooks + Python benchmarks.
2. **Pandas oracle** (`open_fdd.rules`, `open_fdd.analytics`, `open_fdd.reporting`) — cookbook catalog, analytics helpers, Engineering Findings.

**Why it exists:** agents put industry-method calcs into **Excel** for human audit, then optionally **compare honesty against EnergyPlus** — see [Purpose: Excel + EnergyPlus](purpose-excel-energyplus.html).

The ECM API fills the same workbook input cells a human engineer would fill.
It does not replace the visible spreadsheet calculations.

**Production FDD** (DataFusion SQL fault detection) lives in the [GHCR container stack]({{ site.baseurl }}/quick-start/docker-ghcr.html), not this wheel.

**Product freeze / upsell:** [Engineer upsell brief](ENGINEER_UPSELL_BRIEF.html) — customers see ECM via **PyPI → open-fdd**, not vibe tip churn.

**Build handoff / golden example:** [OPENFDD_AGENT_ECM_HANDOFF](OPENFDD_AGENT_ECM_HANDOFF.html) · packaged workbook in-repo under `open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx`.

## Install

```bash
pip install open-fdd                 # ECM only (openpyxl)
pip install "open-fdd[oracle]"       # + pandas rules
pip install "open-fdd[analytics]"    # + analytics helpers (same as oracle)
pip install "open-fdd[reporting]"    # + Engineering Findings extras
pip install "open-fdd[anomaly]"      # + offline anomaly screening (STL, Isolation Forest)
```

For the FastAPI ECM example:

```bash
pip install "open-fdd[ecm-web]"
```

## Oracle rules (pandas)

```python
from open_fdd.rules import RULES, run_rule
```

See also the [Pandas cookbook]({{ site.baseurl }}/rules/cookbook/pandas-cookbook.html).

## Generate a workbook in a few lines

```python
from open_fdd.ecm_engineering import ECMJob

job = (
    ECMJob("Lincoln Middle School")
    .set_global(
        area_ft2=85000,
        electric_rate=0.145,
        gas_rate=0.92,
    )
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

job.save("Lincoln_Middle_School_ECMs.xlsx")
```

The resulting XLSX contains the engineering inputs and formulas for human review.

### Module names vs calculators

```python
from open_fdd.ecm_engineering import list_ecm_modules, list_calculators

list_ecm_modules()   # names accepted by add_ecm (aliases included)
list_calculators()   # independent Python benchmarks (job.calc), not sheet names
```

## CLI

```bash
open-fdd-ecm calculators
open-fdd-ecm demo --out Demo_ECMs.xlsx
```

### Anomaly screening

Offline AHU IO screen of a device folder (`history_wide.csv` + `column_map.json`).
Z-score and MAD are SQL-portable rolling stats. STL and Isolation Forest are
Python-only (`open-fdd[anomaly]`).

```bash
open-fdd-anomaly screen ./AHU_1 --out ./anomaly_out
# defaults: --top-n 5 --max-days 10 --methods zscore,mad,stl,iforest

# Single AHU FDD/RCx Typst (not the BUILDING_100 Overview PDF).
# --month filters every plot. --week pins the RCx window (YYYY-MM-DD, 7 days).
# Web OAT: mapped column, CSV (web_oa_t reindexed onto the BAS clock), or fetch.
# Economizer scatter: x = OAT−RAT, y = MAT−RAT, bottom-left quadrant only.
# build_economizer_delta_points (alias economizer_delta_frame).
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --web-oat ./weather.csv
# April folder (8640 rows @ 5 min). Do not fetch this in CI.
open-fdd-anomaly report ./AHU_1 --out ./april_report --month 2026-04 \
  --web-oat ./open_meteo_april.csv --week 2026-04-06 --compile
open-fdd-anomaly report ./BUILDING --scope building --out ./bldg_report
typst compile ./ahu1_report/report.typ ./ahu1_report/report.pdf
```

## Math & agent rules

- [ECM engineering math]({{ site.baseurl }}/operations/ECM_ENGINEERING_MATH.html)
- [Agent rules](AGENTS_ECM_ENGINEERING.html)
- [PyPI release checklist](PYPI_RELEASE_CHECKLIST.html)
