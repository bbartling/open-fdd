# WattLab-to-WattLab dump parity (Building 100) — 4.4.1 / `sha-2c12c8e`

Oracle: vibe19 Engineering Bundle (`ghcr.io/bbartling/vibe19:latest`, wheel **4.4.0** until Prompt 2 pins **4.4.1**).  
OpenFDD: DataFusion assembler on **`sha-2c12c8e`** (PR #727), health `3.3.0+2c12c8e814a8`. `:nightly` digest matches `sha-2c12c8e` (`sha256:54e6fbf5…123d82`).

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD pin | `sha-2c12c8e` health `3.3.0+2c12c8e814a8` |
| PyPI | **open-fdd 4.4.1** (tag `open-fdd-v4.4.1`, Trusted Publishing) |
| Vibe19 | `:latest` digest `sha256:6a4297b9…e6f54d` (still 4.4.0 wheel; Prompt 2 on Windows) |
| **blockers** | **405** (unchanged vs `sha-8ab0b5e`) |
| accepted | 2690 |
| rows | 3260 |
| stop_rule_met | **false** |

Classifier (A2): blockers are FAULT vs PASS and FAULT∩FAULT hours. N/A-omit and one-sided sensor columns are accepted. FDD blockers 217; remaining sensor_diurnal/stats ~187 are two-sided numeric gaps, not one-sided `mean`.

## Four B100 examples after ECON SQL follow-on (#727)

| ID | vibe19 pandas | OpenFDD SQL `sha-2c12c8e` | Notes |
| --- | ---: | ---: | --- |
| `AHU-DUCTHI` AHU_2 | FAULT **0.5 h** | FAULT **1.83 h** | Unchanged vs #725. Residual ~1.3 h FAULT∩FAULT still a blocker. |
| `ECON-2` AHU_1 | PASS **0 h** | FAULT **1422.92 h** | Still open. Hours **rose** vs 952.5 h after dropping the extra fan AND; 0–100 damper 20 still behaves like raw `20 > 0.42`. `damper_frac` CTE did not fix DataFusion on this historian. |
| `ECON-1` AHU_1 | FAULT **326 h** | PASS **0 h** | Still a FAULT/PASS blocker. Raw damper 20 is not `< 0.05`; cmd-first fan did not produce the pandas 326 h. |
| `CHW-NOLOAD-1` CHILLER_2 | FAULT **524.5 h** | **SKIPPED_MISSING_ROLES** | No false PASS. Skip until load-satisfaction enrichment is mapped. Accepted vs FAULT. |

Do not greenwash: #727 shipped `damper_frac` + pandas fan/equation; B100 ECON-1/2 are still open. Next SQL attempt should inline the percent CASE in the same SELECT as `FROM history` (no later-CTE column), matching the historian `damper_fb_pct` pattern.

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-2c12c8e
docker pull ghcr.io/bbartling/openfdd-central:sha-2c12c8e  # + web/fieldbus/mqtt
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```

No local `docker build`. Vibe19 Prompt 2: [`docs/agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md`](../agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md).
