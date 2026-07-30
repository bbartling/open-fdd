# Engineer upsell brief — open-fdd + PyPI (vibe freeze)

**Date:** 2026-07-30  
**Audience:** product / sales engineering / open-fdd release owners  
**Freeze:** After today — **no more vibe19/vibe20 app updates.** Everything customers see ships through **PyPI packages open-fdd already installs**, then **open-fdd Jobs / MCP / UI**.

---

## The pitch (one paragraph)

We can sell **credible ECM packages** only if the spreadsheet is a real **second set of eyes** on EnergyPlus — industry-method math (opt-start, full-recirc warmup, DAT/DSP/CHW/econ), live Excel formulas, and honest status — not reverse-fitted hours labeled “ballpark.” Dual-AHU SAT reset must **save** energy (we proved **+122 MWh** vs a broken flat-14°C patch that showed **−7 MWh**). Land that in **PyPI → open-fdd**; stop polishing vibe containers.

---

## What the customer gets

| Capability | Why it sells | Proof in hand |
|------------|--------------|---------------|
| **Industry screening vs E+** | Engineer trust: sheet ≠ rubber stamp | `ECM_FULL_PARITY.xlsx` — `Industry_Screening` + `%` gaps |
| **Honest FITTED vs BALLPARK** | Avoid oversell / audit risk | BUG-ECM-018 — fitted FLH no longer greenwashed |
| **DAT / SAT reset that works** | Control ECM that actually pays | BUG-ECM-019 — fixed patch **+122 MWh** / +8.5k therms |
| **Opt-start + OAD 0% recirc** | Matches ESCO calculator language buyers know | SCHED_ALIGN ≈ E+ within **~5%** on Liberty |
| **Twin calibrate workbook** | One artifact for G14 + ECMs | Twin_Calibrate / Architecture / Schedules sheets |

**Talk track:** “We don’t fit the spreadsheet to the model. We check the model against the same methods your ESCO books use — and we fixed the SAT patch that was inventing negative savings.”

---

## What we are shipping (PyPI → open-fdd)

**Not** more vibe tip churn. **Yes** package bumps open-fdd pins.

### Must-have this release train

1. **PyPI:** industry 2nd-eyes workbook export (formulas, FITTED, `%` vs E+, SCHED_ALIGN = run-hour cut + warmup **full recirculation**).  
2. **PyPI:** dual-AHU `sat_reset` = preserve winter dump + raise cool DAT on **both** AHUs (retire flat 14°C / Sys1-only).  
3. **open-fdd:** Compare / cascade UI respects FITTED / FAIL_SIGN; never sell negative SAT; show industry `%` gap.  
4. **open-fdd docs:** mirror BUG-ECM-018 / 019 in [`docs/migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md`](../migration/BUG_REPORT_ECM_SPREADSHEET_VS_EPLUS.md).

### Next upsell (same channel)

Twin export API, massing PNG, `shell_summary`, schedule grids, Jobs “current Twin only” Inputs — all via **PyPI + open-fdd**, not vibe apps.

---

## Objection handling

| Objection | Response |
|-----------|----------|
| “Sheet matches E+ exactly — great!” | Only if status is **FITTED**. Exact match with **BALLPARK** is a bug (018). |
| “SAT showed negative savings” | Broken IDF patch, not the measure. Fixed physics: **+122 MWh**. |
| “Will you keep updating vibe20?” | **No.** Product path is **open-fdd + PyPI** after freeze day. |
| “Can we build Excel in the UI?” | Don’t oversell. Link package-exported notebooks; Gate C stays honest. |

---

## Close criteria (sales-ready)

- [ ] open-fdd release notes cite PyPI bump with 018/019  
- [ ] Demo: Measures `%` columns + Industry_Screening; SAT positive after patch  
- [ ] Compare UI copy matches honesty rules (no fake BALLPARK)  
- [ ] vibe apps marked frozen in internal runbooks  

**Workspace refs (port into PyPI, don’t productize in place):**  
`ECM_FULL_PARITY.xlsx` · `tools/build_full_parity_ecm_workbook_v2.py` · `tools/patch_sat_reset_dual_ahu.py` · `reports/ecm_industry_method_gap.md`

**In-repo golden (build machine):**  
[`examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx`](../../open_fdd/ecm_engineering/examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx) · [OPENFDD_AGENT_ECM_HANDOFF.md](OPENFDD_AGENT_ECM_HANDOFF.md)
