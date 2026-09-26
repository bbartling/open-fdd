# Open-FDD Python package (PyPI)

> **GitHub Pages:** this README is excluded from the docs site (`exclude: README.md`). Published overview lives at [`docs/ecm/index.md`](index.md) / [`overview.md`](overview.md) — section **PyPI agent tools**.

`open-fdd` (PyPI **4.1+**) ships:

1. **ECM engineering** (`open_fdd.ecm_engineering`) — agent-drivable HVAC spreadsheet workbooks + Python benchmarks.
2. **Pandas oracle** (`open_fdd.rules`, `open_fdd.analytics`, `open_fdd.reporting`) — cookbook catalog, analytics helpers, Engineering Findings.

The ECM API fills the same workbook input cells a human engineer would fill.
It does not replace the visible spreadsheet calculations.

**Production FDD** (DataFusion SQL fault detection) lives in the [GHCR container stack](https://bbartling.github.io/open-fdd/quick-start/docker-ghcr.html), not this wheel.

**Product freeze / upsell:** [Engineer upsell brief — open-fdd + PyPI (vibe freeze)](ENGINEER_UPSELL_BRIEF.md) — after 2026-07-30, customers see ECM via **PyPI → open-fdd**, not vibe19/vibe20 tip churn.

**Build handoff / golden example:** [OPENFDD_AGENT_ECM_HANDOFF.md](OPENFDD_AGENT_ECM_HANDOFF.md) · packaged workbook [`examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx`](../../open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx).

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

# set_many / add_ecm already persist; save() is idempotent on the same path
# (BUG-OFDD-ECM-002) and can also copy to another path.
job.save("Lincoln_Middle_School_ECMs.xlsx")
```

The resulting XLSX contains the engineering inputs and formulas for human review.

### Module names vs calculators

```python
from open_fdd.ecm_engineering import list_ecm_modules, list_calculators

list_ecm_modules()   # names accepted by add_ecm (aliases included)
list_calculators()   # independent Python benchmarks (job.calc), not sheet names
```

New in **4.2.0**: `chiller_lockout`, `load_shed`, `schedule_align` / `ahu_sched_align`.

### Honesty / twin compare export (4.2.0)

```python
job.attach_twin_compare({
    "provenance": {"idf_path": "...", "g14_pass": True},
    "inputs": [{"name": "lockout_hours", "value": 612, "provenance": "FITTED_FROM_EPLUS"}],
    "measures": [{
        "measure_id": "ECM-CHILLER-LOCKOUT",
        "name": "Chiller OAT lockout",
        "eplus_source": "cascade",
        "fitted_sheet_kwh": 101580.56,
        "eplus_kwh": 101580.56,
        "hours_provenance": "FITTED_FROM_EPLUS",
    }],
    "demand": {"july_weekday_kw": 420, "july_weekend_kw": 280, "loadshed_kw": 365},
})
job.save("honesty.xlsx")  # Contents, Measures, … (FITTED ≠ independent validation)
```

### IPMVP change-point / G14 (4.4.3)

```python
from open_fdd.ecm_engineering import fit_changepoint, score_g14_monthly, option_c_savings
```

Docs: [IPMVP change-point & G14](ipmvp-changepoint.md). Requires `numpy` (`pip install "open-fdd[oracle]"`).

## Independent benchmark

```python
from open_fdd.ecm_engineering import ECMJob

job = ECMJob("demo")
result = job.calc(
    "fan_affinity",
    design_kw=55.9,
    hours=4100,
    baseline_speed_fraction=0.82,
    proposed_speed_fraction=0.67,
)
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

# Single AHU FDD/RCx PDF. Only this CLI; no build_april_report.py or other local runner.
# --compile writes report.pdf when typst is on PATH.
# --month filters every plot. --week pins the RCx window (YYYY-MM-DD, 7 days).
# Web OAT: mapped column, CSV (web_oa_t reindexed onto the BAS clock), or fetch.
# Economizer scatter: x = OAT−RAT, y = MAT−RAT, bottom-left quadrant only.
# build_economizer_delta_points (alias economizer_delta_frame).
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --compile
open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --web-oat ./weather.csv --compile
# April folder (8640 rows @ 5 min). Do not fetch this in CI.
open-fdd-anomaly report ./AHU_1 --out ./april_report --month 2026-04 \
  --web-oat ./open_meteo_april.csv --week 2026-04-06 --compile
# building folder of device subfolders:
open-fdd-anomaly report ./BUILDING --scope building --out ./bldg_report --compile
```

## Engineering posture

Prefer measured BAS, utility, TAB, nameplate and manufacturer data over defaults.
Generic chiller `%/°F` methods are screening proxies; manufacturer performance
maps or calibrated EnergyPlus should replace them when stronger estimates are needed.
