# WattLab-to-WattLab dump parity (Building 100) — 4.4.1 / `sha-8ab0b5e`

Oracle: vibe19 Engineering Bundle (`ghcr.io/bbartling/vibe19:latest`, wheel **4.4.0** until Prompt 2 pins **4.4.1**).  
OpenFDD: DataFusion assembler on **`sha-8ab0b5e`** (PR #725), health `3.3.0+8ab0b5e347d8`.

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD pin | `sha-8ab0b5e` health `3.3.0+8ab0b5e347d8` |
| PyPI | **open-fdd 4.4.1** (tag `open-fdd-v4.4.1`, Trusted Publishing) |
| Vibe19 | `:latest` digest `sha256:6a4297b9…e6f54d` (still 4.4.0 wheel; Prompt 2 on Windows) |
| **blockers** | **405** (was 2596 on the 4.4.0 / `sha-9e280ae` cycle) |
| accepted | 2690 |
| rows | 3260 |
| stop_rule_met | **false** |

Classifier (A2): blockers are FAULT vs PASS and FAULT∩FAULT hours. N/A-omit and one-sided sensor columns are accepted. FDD blockers 217; remaining sensor_diurnal/stats ~187 are two-sided numeric gaps, not one-sided `mean`.

## Four B100 examples after SQL patch

| ID | vibe19 pandas | OpenFDD SQL `sha-8ab0b5e` | Notes |
| --- | ---: | ---: | --- |
| `AHU-DUCTHI` AHU_2 | FAULT **0.5 h** | FAULT **1.83 h** | Overnight 7" fan-off **cleared** (was 1341 h). Residual ~1.3 h FAULT∩FAULT still a blocker. |
| `ECON-2` AHU_1 | PASS **0 h** | FAULT **952.5 h** | Still the unnormalized-damper class on this historian; not cleared. |
| `ECON-1` AHU_1 | FAULT **326 h** | PASS **0 h** | Still a FAULT/PASS blocker (fan-cmd 0–100 vs status). |
| `CHW-NOLOAD-1` CHILLER_2 | FAULT **524.5 h** | **SKIPPED_MISSING_ROLES** | No false PASS. Skip until load-satisfaction enrichment is mapped. Accepted vs FAULT. |

Do not greenwash: A1 fixed DUCTHI physics and CHW skip; ECON-1/2 remain open on B100.

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-8ab0b5e
docker pull ghcr.io/bbartling/openfdd-central:sha-8ab0b5e  # + web/fieldbus/mqtt
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```

No local `docker build`. Vibe19 Prompt 2: [`docs/agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md`](../agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md).
