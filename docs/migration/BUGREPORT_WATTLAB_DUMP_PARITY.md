# WattLab-to-WattLab dump parity (Building 100) — vibe19 4.4.1 / `sha-5aebdfc`

Oracle: vibe19 Engineering Bundle `ghcr.io/bbartling/vibe19:latest` digest `sha256:101126ab…32760f07`, wheel **4.4.1**, catalog `2e684dbb…cba9` (playground PR **#92** `4b71061`). Diagnostic dump includes `vav_health_matrix.csv`, `mech_cooling_oat_bins.csv`, `motor_hours.csv`, `motor_weekly.csv`.

OpenFDD: DataFusion on **`sha-5aebdfc`** (PR **#731** CAST DOUBLE + `>= 1.5` percent gate). Health `3.3.0+5aebdfc54434`. `:nightly` digest matches central `sha256:a56846e2…4006351a`. Stack: `OPENFDD_IMAGE_TAG=sha-5aebdfc` `react-ot --no-pull`. No local docker/cargo build. Image SQL contains the CAST gate (docker exec confirmed).

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-16 |
| OpenFDD pin | `sha-5aebdfc` health `3.3.0+5aebdfc54434` |
| PyPI / vibe19 wheel | **open-fdd 4.4.1** |
| Vibe19 | `:latest` = `:develop` `sha256:101126ab…32760f07` |
| **blockers** | **449** |
| accepted | 2689 |
| rows | 3303 |
| stop_rule_met | **false** |

`vav_health_matrix.csv` is present on both sides. 44 of 449 blockers are per-equipment `vav_health` score/label gaps, not a missing file.

## Synthetic-59 ground truth (expected_faults.csv, ~1 h planted)

| Side | Target match |
| --- | --- |
| vibe19 pandas | **59/59** (prior cycle; damper 0–1) |
| OpenFDD SQL | **59/59** on `sha-5aebdfc` |
| Overview analytics soak | **PASS** (prior cycle) |

GHA oracle tests on #731: damper **20** + OAT 70 → ECON-2 **0 h**; damper **0** + fan-cmd **60** → ECON-1 hours **> 0**; fraction **0.55** still faults ECON-2.

## Four B100 FDD examples (`sha-5aebdfc` after CAST / `>= 1.5`)

AHU_1 parquet `oa_damper_pct` is **Float64**, min 0 max 100 (not Utf8). When `oa_t > 63`, damper median/p90 is **100**, so fraction 1.0 **does** exceed 0.42. SQL **1422.92 h** matches `frac(damper)>0.42` **and** raw `damper>0.42` on this historian (17075 samples). The “min OA 20 compared as 20 > 0.42” story does **not** hold for current parquet.

| ID | vibe19 pandas | OpenFDD SQL | Notes |
| --- | ---: | ---: | --- |
| `AHU-DUCTHI` AHU_2 | FAULT **0.5 h** | FAULT **1.83 h** | Residual ~1.3 h FAULT∩FAULT |
| `ECON-2` AHU_1 | PASS **0 h** | FAULT **1422.92 h** | Unchanged hours. CAST is live; historian damper is ~100% in high OAT, not stuck at min OA 20. Pandas still 0 h → **series/equation mismatch**, not DF types. |
| `ECON-1` AHU_1 | FAULT **326.08 h** | PASS **0 h** | Unchanged. SQL sees damper open (not stuck closed). |
| `CHW-NOLOAD-1` CHILLER_2 | FAULT **524.5 h** | **SKIPPED_MISSING_ROLES** | No false PASS; accepted |

Do not claim #731 cleared B100 ECON vs pandas. Next: which AHU_1 point pandas uses for econ damper vs historian `oa_damper_pct` (and OAT), not another CAST.

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-5aebdfc
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
python3 scripts/synthetic_59_target_pair_soak.py --side ofdd
```
