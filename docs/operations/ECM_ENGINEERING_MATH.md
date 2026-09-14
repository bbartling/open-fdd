---
title: Engineering calcs
parent: PyPI agent tools
nav_order: 2
permalink: /operations/ECM_ENGINEERING_MATH.html
---

# Engineering calculations (agent → Excel)

These are the **industry-method screens** an AI agent (or engineer) drives through `open_fdd.ecm_engineering`. Python can referee the same math via `job.calc(...)`; the **Excel workbook** keeps live formulas for human review.

Install: `pip install open-fdd` (extras: `[oracle]`, `[analytics]`, `[reporting]`).

**Story first:** [Purpose — Excel + EnergyPlus]({{ site.baseurl }}/ecm/purpose-excel-energyplus.html).  
**Product FDD** remains DataFusion on GHCR — this page is PyPI ECM only.

---

## How agents put calcs in Excel

1. Choose an ECM module name from `list_ecm_modules()` (friendly aliases for `add_ecm`).
2. Supply **inputs** from evidence (BAS trends, meters, TAB, nameplates, utilities) — never invent when the human can supply.
3. Call `job.add_ecm(...)` / `set_global(...)` — writes **input cells** only.
4. Call `job.save(...)` — engineer opens the `.xlsx` and audits formula-driven savings.
5. Optional: `attach_twin_compare(...)` for EnergyPlus honesty sheets.

```python
from open_fdd.ecm_engineering import ECMJob, list_ecm_modules, list_calculators

list_ecm_modules()    # sheet modules accepted by add_ecm
list_calculators()    # independent Python benchmarks (job.calc), not sheet names

job = ECMJob("Example School").set_global(electric_rate=0.14)
job.add_ecm(
    "static_pressure_reset",
    fan_kw=55.9,
    hours=4100,
    baseline_speed=0.82,
    proposed_speed=0.67,
)
job.save("example_ecms.xlsx")
```

---

## Fan affinity (static pressure / VFD reset)

Affinity laws for variable-speed fans (power ∝ speed³ when pressure follows affinity):

$$
P_{\mathrm{prop}} = P_{\mathrm{base}} \left(\frac{N_{\mathrm{prop}}}{N_{\mathrm{base}}}\right)^{3}
$$

$$
\Delta E \approx (P_{\mathrm{base}} - P_{\mathrm{prop}}) \times h
$$

| Symbol | Meaning |
|--------|---------|
| $$P$$ | Fan power (kW) |
| $$N$$ | Relative speed (0–1) |
| $$h$$ | Annual operating hours |

Typical agent inputs for `static_pressure_reset`: `fan_kw`, `hours`, `baseline_speed`, `proposed_speed`.

---

## Boiler / heating efficiency reset (sketch)

When baseline and proposed seasonal efficiencies differ at similar load:

$$
\Delta \mathrm{therms} \approx Q_{\mathrm{base}} \left(1 - \frac{\eta_{\mathrm{base}}}{\eta_{\mathrm{prop}}}\right)
$$

Agent module example: `boiler_reset` with `base_therms`, `base_eff`, `prop_eff` (plus site gas rate on globals for $). Exact cell map lives in the packaged workbook template — agents fill inputs; formulas stay in Excel.

---

## Honesty vs EnergyPlus (why the math exists)

Industry screens are **independent** of the EnergyPlus IDF. After a twin cascade:

- Compare sheet kWh / therms to `ep_*` results.
- Label **FITTED** if hours were reverse-fitted to match the model.
- Label **NO_EP** when no patch exists — do not invent modeled savings.
- Treat **FAIL_SIGN** as a model or measure problem, not a marketing opportunity.

Full workflow: [Purpose — Excel + EnergyPlus]({{ site.baseurl }}/ecm/purpose-excel-energyplus.html).  
Pitch + proof: [Engineer upsell brief]({{ site.baseurl }}/ecm/ENGINEER_UPSELL_BRIEF.html).

---

## Agent skill pointers

| Need | Tool |
|------|------|
| ECM workbook + calcs | PyPI `open_fdd.ecm_engineering` — [Agent rules]({{ site.baseurl }}/ecm/AGENTS_ECM_ENGINEERING.html) |
| Central REST / FDD | `openfdd-mcp` stdio |
| BACnet wire debug (read-only) | [rusty-bacnet-mcp]({{ site.baseurl }}/mcp-agents/companion-rusty-bacnet-mcp.html) |
| OT poll policy | [BACNET_OT_POLICY]({{ site.baseurl }}/operations/BACNET_OT_POLICY.html) — fieldbus **never** cloud |

## PyPI refresh

When calcs or these docs change: follow the [PyPI release checklist]({{ site.baseurl }}/ecm/PYPI_RELEASE_CHECKLIST.html) and republish via Trusted Publishing.
