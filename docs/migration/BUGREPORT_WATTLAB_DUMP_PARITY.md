# WattLab-to-WattLab dump parity (Building 100) — vibe19 4.4.1 / `sha-8525cfc`

Oracle: vibe19 Engineering Bundle `ghcr.io/bbartling/vibe19:latest` digest `sha256:101126ab…32760f07`, wheel **4.4.1**, catalog `2e684dbb…cba9` (playground PR **#92** `4b71061`). Diagnostic dump includes `vav_health_matrix.csv`, `mech_cooling_oat_bins.csv`, `motor_hours.csv`, `motor_weekly.csv`.

OpenFDD: DataFusion on **`sha-8525cfc`** (PR #729 inline damper CASE), health `3.3.0+8525cfca140f`. `:nightly` digest matches (`sha256:1b2a9128…be1d8c`). Stack: `OPENFDD_IMAGE_TAG=sha-8525cfc` `react-ot --no-pull`. No local docker/cargo build.

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD pin | `sha-8525cfc` health `3.3.0+8525cfca140f` |
| PyPI / vibe19 wheel | **open-fdd 4.4.1** |
| Vibe19 | `:latest` = `:develop` `sha256:101126ab…32760f07` |
| **blockers** | **449** (was 405 before vav_health row compare) |
| accepted | 2689 |
| rows | 3303 |
| stop_rule_met | **false** |

`vav_health_matrix.csv` is present on both sides. Missing-oracle is a **blocker** again (Prompt 2 closed). 44 of 449 blockers are per-equipment `vav_health` score/label gaps, not a missing file.

## Synthetic-59 ground truth (expected_faults.csv, ~1 h planted)

| Side | Target match |
| --- | --- |
| vibe19 pandas | **59/59** |
| OpenFDD SQL | **59/59** |
| Overview analytics soak | **PASS** (runtime + mech OAT bins) |

Eyeball: ECON-1/2 synth damper is **0–1** (fault hour damper 0.0 / 1.0). That is why SQL `damper_frac` CTE matches goldens here and still fails B100 **0–100**.

## Four B100 FDD examples (`sha-8525cfc` after inline CASE)

| ID | vibe19 pandas | OpenFDD SQL | Notes |
| --- | ---: | ---: | --- |
| `AHU-DUCTHI` AHU_2 | FAULT **0.5 h** | FAULT **1.83 h** | Residual ~1.3 h FAULT∩FAULT |
| `ECON-2` AHU_1 | PASS **0 h** | FAULT **1422.92 h** | Unchanged vs CTE alias. Image SQL has inline `> 1.0` `/100`; hours still match raw `20 > 0.42`. |
| `ECON-1` AHU_1 | FAULT **326.08 h** | PASS **0 h** | Unchanged |
| `CHW-NOLOAD-1` CHILLER_2 | FAULT **524.5 h** | **SKIPPED_MISSING_ROLES** | No false PASS; accepted |

Do not claim the inline CASE cleared B100. Next: prove DataFusion comparison types on `oa_damper_pct` (CAST DOUBLE / `>= 1.5`) in GHA fixtures with **0–100** damper, not only 0–1 Synthetic-59.

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-8525cfc
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/wattlab_parity_oracle_dump.py
python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
python3 scripts/synthetic_59_target_pair_soak.py --side both
```
