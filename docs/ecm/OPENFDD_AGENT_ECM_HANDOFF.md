# Handoff — Liberty ECM full-parity example → open-fdd + PyPI

**Date:** 2026-07-30  
**Audience:** build/publish Cursor agents (this repo)  
**Twin characterization SoT (test machine):** `runs/geo_b100_dual_ahu_shape_ops11` (dual-AHU G14 PASS)  
**Product path:** **PyPI `open-fdd` → open-fdd Jobs / MCP / UI**. vibe19/vibe20 tip churn is **frozen** after soak day — see [ENGINEER_UPSELL_BRIEF.md](ENGINEER_UPSELL_BRIEF.md).

Test/prototype workspaces may produce artifacts but **must not** publish PyPI or bump pins. **This repository** is where wheels are built, tested, published, and pins bumped.

---

## Golden example (in-repo)

| Artifact | Path | Role |
|----------|------|------|
| **Workbook** | [`open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx`](../../open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx) | Golden agent / Compare honesty example |
| **Upsell brief** | [ENGINEER_UPSELL_BRIEF.md](ENGINEER_UPSELL_BRIEF.md) | Sales + release close criteria |
| **Bug register** | [`docs/migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md`](../migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md) | BUG-ECM-018 / 019 |

**Workspace-only sources to port from (do not commit proprietary calculators):**

| Artifact | Typical test-machine path |
|----------|---------------------------|
| Findings JSON | `reports/notebooks/full_parity_ecm/full_parity_findings.json` |
| Compare JSON | `reports/ecm_full_parity_compare.json` |
| Builder | `tools/build_full_parity_ecm_workbook_v2.py` |
| SAT IDF patch | `tools/patch_sat_reset_dual_ahu.py` |
| SAT sim proof | `runs/…/ecm_sat_reset_fixed/sat_fixed_vs_baseline.json` (+122 MWh) |
| Method gap notes | `reports/ecm_industry_method_gap.md` |

**Never commit:** `private/reference/calculators.zip`, `.artifacts/calcs_ref/**`, UHLtool, CCPS books — proprietary inspiration only.

---

## Test results (characterization machine)

### Spreadsheet honesty

- Measures: Excel formulas over named Inputs; status **FITTED** / **BALLPARK** (not fake BALLPARK on reverse-solved FLH).
- Columns: `fitted_sheet_kwh`, `eplus_kwh`, `pct_diff_fitted_vs_eplus`, `industry_screen_kwh`, `pct_diff_industry_vs_eplus`.
- **`pct_diff_fitted ≈ 0%`** is expected for FITTED rows (hours backsolved from E+) — **not** validation.
- **Real 2nd eyes:** `pct_diff_industry_vs_eplus` (Industry_Screening sheet).

### SAT / DAT (BUG-ECM-019)

| Source | kWh saved |
|--------|-----------|
| Broken tip cascade (flat 14°C / Sys1-only) | **−7,317** |
| Dual-AHU patch (preserve dump, both AHUs) | **+122,158** (+8,456 therms) |
| Industry DAT screen (same sign) | ~**+72,128** |

### Industry vs E+ (selected)

| measure_id | industry vs eplus (approx) |
|------------|----------------------------|
| ECM-AHU-SCHED-ALIGN | **~−5%** (opt-start + OAD 0% recirc) |
| ECM-DSP-RESET | ~−30% |
| ECM-SAT-RESET (fixed eplus) | ~−41% |
| ECM-CHW-RESET | ~−50% |
| ECM-ECON-REPAIR | large +% (industry richer than fitted stub) |

---

## Build-machine tasks (this repo)

1. Port WattLab-owned formulas from the full-parity builder into **`open_fdd.ecm_engineering`** / notebook export APIs.  
2. Port dual-AHU `sat_reset` preserve-dump into the EnergyPlus patch path open-fdd / WattLab already consumes.  
3. Compare / Jobs UI: show **FITTED vs industry %**; never green-check fitted exact matches; never sell negative SAT.  
4. Keep BUG-ECM-018 / 019 mirrored on the spreadsheet↔E+ register.  
5. Keep skill [`openfdd-ecm-engineering`](../../openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md) pointed at this Liberty example.  
6. Build wheel → test wheel → publish → bump pins; append `openfdd_agent_spec/SESSION_LOG.md`.

### Agent prompt (paste)

```text
You are on the BUILD/PUBLISH machine (open-fdd repo). Liberty dual-AHU
ECM_FULL_PARITY.xlsx is the golden example under
open_fdd/ecm_engineering/examples/liberty_dual_ahu/.

Tasks:
1) Port industry screening + workbook export into open_fdd.ecm_engineering (PyPI).
2) Port sat_reset dual-AHU preserve-dump into the published EnergyPlus patch path.
3) Update Compare/Jobs honesty (FITTED, pct_diff_industry, no negative SAT sell).
4) Mirror BUG-ECM-018/019; keep openfdd-ecm-engineering skill linked to this example.
5) Build wheel → test that wheel → publish → bump pins. Append SESSION_LOG.

Proprietary calculators were inspiration only — ship WattLab-owned formulas only.
```

---

## Product rules (keep forever)

1. Spreadsheet = **2nd set of eyes**; E+ must not be way off from industry method.  
2. Never label reverse-solved FLH as independent **BALLPARK** (**BUG-ECM-018**).  
3. Never flatten dialed Dump DAT to year-round mid SAT on dual-AHU (**BUG-ECM-019**).  
4. Opt-start industry = cut run hours **+** warmup/cooldown **OAD 0% / full recirculation**.  
5. UHLtool / CCPS books: local inspiration only — **never commit**.
