# Open-FDD Python package (PyPI)

`open-fdd` (PyPI **4.1+**) ships:

1. **ECM engineering** (`open_fdd.ecm_engineering`) — agent-drivable HVAC spreadsheet workbooks + Python benchmarks.
2. **Pandas oracle** (`open_fdd.rules`, `open_fdd.analytics`, `open_fdd.reporting`) — vibe19 catalog, analytics helpers, Engineering Findings.

The ECM API fills the same workbook input cells a human engineer would fill.
It does not replace the visible spreadsheet calculations.

**Production FDD** (DataFusion SQL fault detection) lives in the [GHCR container stack](https://bbartling.github.io/open-fdd/quick-start/docker-ghcr.html), not this wheel.

**Product freeze / upsell:** [Engineer upsell brief — open-fdd + PyPI (vibe freeze)](ENGINEER_UPSELL_BRIEF.md) — after 2026-07-30, customers see ECM via **PyPI → open-fdd**, not vibe19/vibe20 tip churn.

**Build handoff / golden example:** [OPENFDD_AGENT_ECM_HANDOFF.md](OPENFDD_AGENT_ECM_HANDOFF.md) · packaged workbook [`examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx`](../../open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx).

## Install

```bash
pip install open-fdd                 # ECM only (stdlib)
pip install "open-fdd[oracle]"       # + pandas rules / analytics
pip install "open-fdd[reporting]"    # + Engineering Findings extras
pip install "open-fdd[vibe19]"       # playground meta-extra
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

job.save("Lincoln_Middle_School_ECMs.xlsx")
```

The resulting XLSX contains the engineering inputs and formulas for human review.

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

## Engineering posture

Prefer measured BAS, utility, TAB, nameplate and manufacturer data over defaults.
Generic chiller `%/°F` methods are screening proxies; manufacturer performance
maps or calibrated EnergyPlus should replace them when stronger estimates are needed.
