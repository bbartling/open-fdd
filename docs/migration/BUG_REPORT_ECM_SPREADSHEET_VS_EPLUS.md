# BUG_REPORT — ECM spreadsheet ↔ EnergyPlus / Studio

**Date:** 2026-07-29  
**Twin SoT:** `geo_b100_6stack_shape_r56_sched_mild` (G14 PASS)  
**Artifacts (not bugs):** `reports/notebooks/full_parity_ecm/ECM_FULL_PARITY.xlsx` · `reports/ecm_full_parity_compare.json` · `tools/build_full_parity_ecm_workbook.py`

**Git SoT (keep in sync):**
- playground vibe20: `vibe_code_apps_20/vibe20_agent_spec/docs/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md`
- open-fdd (combined product): `docs/migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md`
- vibe19 pointer: `vibe_code_apps_19/vibe19_agent_spec/docs/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md`

Workspace copies of artifacts live under Studio `/data` (`wattlab_workspace/reports/…`). Do not commit client workbooks to git.

Screening proof (full-parity book): **8 BALLPARK / 0 DIVERGE / 0 NO_EP** — not M&V.

Twin / WattLab Studio / EnergyPlus patch + notebook builder code primarily lives in playground **vibe20**. open-fdd Jobs / ECM honesty (`honesty.openfdd`, cascade-if-ready) must stay aligned with this register when the combined UI surfaces Compare / ECMs.

---

## Open bugs

| ID | Status | Summary |
|----|--------|---------|
| **BUG-ECM-001** | Open | Compare CLI exists; still no rewrite of Compare sheet **inside** agent xlsx; no demand (kW) columns in Compare contract. |
| **BUG-ECM-002** | Open | `FORMULA_ESCO_*` map incomplete for econ / CHW reset / load-shed **kW**; full-parity book bypasses with MCP-calibrated Inputs. |
| **BUG-ECM-003** | Open | Dump / Twin / eio sizing + FLH not auto-applied on `wattlab notebook agent-build` (manual builders exist). |
| **BUG-ECM-004** | Open | Polished `g36_airside_controls` package ignores `--ecms`. |
| **BUG-ECM-005** | Partial | Registry still missing product patches for enthalpy econ / CHW OA reset / true occ-standby. MCP prototypes work (`prototype_no_ep_eplus_patches.py`) but are **not** in `wattlab.energyplus.patches.registry`. Per-VAV occ impossible on 1-zone/floor Twin. |
| **BUG-ECM-006** | Open | Cascade measure set ⊂ workbook set — Studio / Compare must keep `NO_EP` honest when registry lacks a patch (do not invent E+ kWh). |
| **BUG-ECM-007** | Open | Agent Excel lacks ±50% honesty / BALLPARK column vs E+. |
| **BUG-ECM-010** | Open | Agents skip EnergyPlus-MCP and re-read old cascade when enhancing sims (process). |
| **BUG-ECM-011** | Open | Demand (kW) missing from py → Excel / Studio Compare API. |
| **BUG-ECM-012** | Partial | Load-shed DR not in product agent Excel / cascade; workaround tool `load_shed_demand_screen.py` exists. |
| **BUG-ECM-014** | Open (doc) | Calendar FanAvail / OAT-bin hours ≠ formula FLH. Pasting calendar into Inputs over-predicts vs E+. Fix: Matchup calendar + FLH Inputs (`build_eplus_matched_ecm_workbook.py` / full-parity builder). |
| **BUG-ECM-015** | Open | Studio **ECMs** tab does not show full-parity sheet↔E+ results. Page uses `reports/ecm_compare.json` with spreadsheet side `pending_external`; agent xlsx retired; legacy download only globs top-level `notebooks/*.xlsx` (misses `full_parity_ecm/`). |

---

## Fixed

| ID | Notes |
|----|-------|
| **BUG-ECM-008** | Studio G14 iteration chart mixed B50 + B100 — fixed in playground [#65](https://github.com/bbartling/py-bacnet-stacks-playground/pull/65) (`7b26df9`). Per-building dial history + Building filter; best picker scoped within filter. Combined open-fdd Studio must keep the same rule when Twin UI is shared. |
| **BUG-ECM-009** | `score_g14_monthly` writes elec + gas absolutes (tools). |
| **BUG-ECM-013** | Reclassified as **ENH-ECM-009** (flexible `vav_ahu_controls` package / process — not a defect). |

---

## Enhancements

| ID | Priority | Ask |
|----|----------|-----|
| **ENH-ECM-001** | High | Wire full-parity Compare into Studio ECMs: populate `ecm_compare.json` `ss_*` + `ep_*` from `ecm_full_parity_compare.json` (or rebuild path) so the Streamlit table shows the 8-measure ballpark. |
| **ENH-ECM-002** | High | Promote MCP prototypes (enthalpy econ, CHW OA reset, occ floor proxy) into product patch registry + cascade. |
| **ENH-ECM-003** | High | Auto on `agent-build`: eio tons/fan HP + Twin AMY calendar + FLH Inputs (collapse BUG-ECM-003). |
| **ENH-ECM-004** | Med | Write Compare status / ±50% honesty back into xlsx Compare sheet (BUG-ECM-001 / 007). |
| **ENH-ECM-005** | Med | Demand + load-shed columns in Excel + Studio (BUG-ECM-011 / 012); default DR fraction from July MCP pair (~0.13 on B100 r56). |
| **ENH-ECM-006** | Med | Nested notebook picker / download under `reports/notebooks/**` (or promote `ECM_FULL_PARITY.xlsx` to product path). |
| **ENH-ECM-007** | Med | Honor `--ecms` on `g36_airside_controls` (BUG-ECM-004). |
| **ENH-ECM-008** | Done | Filter Studio G14 chart / best-run picker by building — shipped with BUG-ECM-008 / [#65](https://github.com/bbartling/py-bacnet-stacks-playground/pull/65). |
| **ENH-ECM-009** | Low | Default package builds from `VAV_AHU_CONTROLS_ECM_PACKAGE.json` (was BUG-ECM-013 — process/enhancement, not a defect). |
| **ENH-ECM-010** | Low | Skills / `AGENT_CONTEXT` / companion doc prefer full-parity workbook + FLH rules (keep in sync with this file). |

---

## Out of scope here

- vibe19/20 ops BUG-061–064 (tip through `56f6e7b`+)
- open-fdd SQL ↔ pandas parity
- Investment-grade M&V / IPMVP
- Container / GHCR refresh (deferred — more ECM work coming)

---

## Sync rule

Product fixes for Twin / Studio / ECM Excel in **vibe20** must be mirrored or tracked in **open-fdd** (combined product) and noted from **vibe19** agent docs when FDD dumps feed the same ECM path. Do not leave this register drift between repos.
