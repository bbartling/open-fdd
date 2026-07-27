# Open-FDD ECM Engineering

`open-fdd` (PyPI 4.x) packages two complementary engineering surfaces:

1. **Enhanced Excel ECM workbook** — the human-auditable source of truth.
2. **Independent Python benchmark functions** — machine-friendly checks for AI agents, APIs and EnergyPlus comparisons.

The Python API fills the same workbook input cells a human engineer would fill.
It does not replace the visible spreadsheet calculations.

**Production FDD** (DataFusion SQL fault detection) lives in the [GHCR container stack](https://bbartling.github.io/open-fdd/quick-start/docker-ghcr.html), not this wheel.

## Install

```bash
pip install open-fdd
```

For the FastAPI example:

```bash
pip install "open-fdd[ecm-web]"
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
