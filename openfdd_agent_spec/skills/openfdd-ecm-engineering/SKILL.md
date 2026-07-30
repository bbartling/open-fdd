---
name: openfdd-ecm-engineering
description: >-
  Use when migrating or changing generic ECM math in open_fdd.ecm_engineering,
  publishing PyPI ECM workbook exports, or Compare honesty (FITTED vs industry).
  Triggers on: ECM, fan affinity, scheduling bins, full-parity workbook,
  Industry_Screening, BUG-ECM-018, BUG-ECM-019, sat_reset, open-fdd PyPI wheel.
---

# ECM engineering

Canonical generic math: `open_fdd.ecm_engineering` (PyPI).
EnergyPlus IDF surgery stays out of `openfdd-mcp`; patch/sim via EnergyPlus-MCP / WattLab runner.

**vibe freeze (2026-07-30+):** do not polish vibe19/vibe20 tips as the product path.
Ship spreadsheet + honesty through **PyPI → open-fdd**. See
`docs/ecm/ENGINEER_UPSELL_BRIEF.md` and `docs/ecm/OPENFDD_AGENT_ECM_HANDOFF.md`.

## Golden example (Liberty dual-AHU)

Packaged workbook:

```text
open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx
```

Characterization twin (test machine): `runs/geo_b100_dual_ahu_shape_ops11`.

Rules:

- Spreadsheet = **2nd set of eyes** on E+ (industry method), not a rubber stamp.
- Never label reverse-solved FLH as independent **BALLPARK** (**BUG-ECM-018** → **FITTED**).
- Dual-AHU `sat_reset` must preserve winter dump + raise cool DAT on **both** AHUs
  (**BUG-ECM-019** — fixed **+122 MWh** vs broken flat-14°C **−7 MWh**).
- Opt-start industry = cut run hours + warmup/cooldown **OAD 0% / full recirculation**.

## Migration pattern

```text
inventory → golden/characterize → implement/confirm in Open-FDD
→ parity → switch adapter → delete twin → regression → docs → PyPI bump
```

## Already delegated (do not re-port)

fan_affinity, schedule_reduction, outside_air_sensible, kw_per_ton_improvement,
boiler_efficiency_improvement, scheduling_fan/cooling/heating_bins.

Keepers: playground `vibe_code_apps_20/docs/OPENFDD_ECM_TWINS.md` (historical).

## Result contracts

Return enough detail (summary, bins, assumptions, warnings, provenance,
`fitted` vs `industry` status) so adapters do not recompute formulas and UI
never green-checks fitted exact matches as independent validation.
