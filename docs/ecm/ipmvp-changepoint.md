---
title: IPMVP change-point & G14
parent: PyPI agent tools
nav_order: 5
permalink: /ecm/ipmvp-changepoint.html
---

# IPMVP change-point & ASHRAE G14 (pandas oracle)

PyPI helpers for **Option C–style** weather-normalized baselines and **Guideline 14**
calibration scores. Live in `open_fdd.ecm_engineering` (also re-exported from
`open_fdd.analytics`). **Not** product DataFusion FDD — notebooks, twin honesty,
and Wave S4 SQL twin characterization only.

Install: `pip install "open-fdd[oracle]"` (needs `numpy` for change-point fits).

External algorithm reference: [Camber](https://github.com/yroussev/camber) (Apache-2.0).
Open-FDD ports are clean-room IMT/IPMVP shapes — **never** vendor Camber into GHCR
central/web or treat `camber serve` as product UI.

---

## G14 monthly / hourly gates

| Granularity | \|NMBE\| max | CVRMSE max |
|-------------|-------------:|-----------:|
| Monthly (calibrated simulation) | 5% | 15% |
| Hourly | 10% | 30% |

```python
from open_fdd.ecm_engineering import score_g14_monthly, score_g14_fuels

measured = [1200, 1100, 900, 850, 700, 650, 800, 950, 1000, 1050, 1150, 1250]
modeled = [1180, 1120, 910, 840, 710, 640, 790, 960, 1010, 1040, 1160, 1240]

s = score_g14_monthly(measured, modeled, n_params=4, fuel="elec")
assert s.pass_  # |NMBE| ≤ 5% and CVRMSE ≤ 15%

both = score_g14_fuels(
    elec_measured=measured,
    elec_predicted=modeled,
    gas_measured=measured,
    gas_predicted=modeled,
)
assert both["pass"]
```

Formulas (ASHRAE Guideline 14):

$$
\mathrm{NMBE} = 100 \cdot \frac{\sum (m_i - \hat{m}_i)}{(n-p)\,\bar{m}}
$$

$$
\mathrm{CV(RMSE)} = 100 \cdot \frac{\sqrt{\sum (m_i - \hat{m}_i)^2 / (n-p)}}{\bar{m}}
$$

where \(m_i\) is measured, \(\hat{m}_i\) predicted, \(n\) samples, \(p\) model parameters, and \(\bar{m}\) the mean of measured.
---

## Change-point models (2P / 3P / 4P / 5P)

Independent variable is usually outdoor dry-bulb (°F); dependent is period energy (kWh, therms, …).

| Kind | Shape |
|------|--------|
| `2P` | linear: Y = a + b·X |
| `3PH` | heating: Y = a + b·(β − X)₊ |
| `3PC` | cooling: Y = a + b·(X − β)₊ |
| `4P` | dual slope, one change-point β |
| `5P` | dual slope, heating + cooling change-points |

```python
import numpy as np
from open_fdd.ecm_engineering import fit_changepoint, select_changepoint, option_c_savings

oat_f = np.linspace(30, 90, 48)
kwh = 200 + 8 * np.maximum(oat_f - 55, 0)

model = fit_changepoint(oat_f, kwh, kind="3PC")
# or: model = select_changepoint(oat_f, kwh)

# Reporting period: same weather, lower use → positive savings
savings = option_c_savings(model, reporting_x=oat_f, reporting_y=kwh * 0.9)
print(savings["savings_total"], savings["baseline_kind"])
```

Same entry points via `open_fdd.analytics` for oracle notebooks that already import analytics.

---

## Dual catalog — Camber ↔ Open-FDD role aliases (doc only)

Until Wave S4 SQL M&V twins land, this table is **documentation only** — not a
runtime adapter.

| Concept | Camber-ish / IMT | Open-FDD package / SQL role |
|---------|------------------|-----------------------------|
| Outdoor temperature \(X\) | `temp`, OAT | `outside-air-temp`, `oa_t`, weather `dry_bulb_f` / `web-outside-air-temp` |
| Energy \(Y\) (electric) | `energy`, kWh | `elec-power` → monthly kWh, `kwh`, UTIL monthly bills |
| Energy \(Y\) (gas) | gas / therms | `gas-flow` / `gas-rate`, UTIL gas bills |
| Period grain | daily / monthly | package utilities monthly; historian resample in oracle |
| Fit quality | CVRMSE / NMBE | `score_g14*` / model `.cvrmse_pct` |
| Product charts | Camber UI / serve | **Metering** radios + future DataFusion `/api/analytics/*` (S4) |

---

## Boundary

| Layer | Owns |
|-------|------|
| This module (PyPI) | Clean-room math + twin honesty helpers |
| Product GHCR | DataFusion SQL FDD / analytics — no pandas in request path |
| Soft-OPEN | Full Camber family ports, PyPI publish tip, SQL twins (Wave S4) |

Related: [Engineering calcs](engineering-calcs.html) · [Pandas FDD cookbook](../rules/cookbook/pandas-cookbook.html) · [Purpose — Excel + EnergyPlus](purpose-excel-energyplus.html)
