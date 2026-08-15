# WattLab / Vibe19 parity — Building 100 (OpenFDD 4.4.1 / `sha-2c12c8e`)

Dump-vs-dump after ECON-1/2 SQL follow-on (PR **#727**). Oracle remains GHCR vibe19 until Windows Prompt 2 pins PyPI **4.4.1**. OpenFDD is DataFusion JWT APIs. GHCR `:nightly` digest matches `sha-2c12c8e`.

Working copy: `reports/wattlab-parity/` (gitignored artifacts).

## Cycle header

| Side | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD git | `2c12c8e` (#727) |
| OpenFDD image | `ghcr.io/bbartling/openfdd-*:sha-2c12c8e` |
| Central health | `3.3.0+2c12c8e814a8` |
| `/api/fdd/rules` | **66** (62 pandas + 4 SQL analytics) |
| PyPI (vibe19 should pin) | **4.4.1** (`open-fdd-v4.4.1`) |
| Vibe19 image wheel today | still **4.4.0** until Prompt 2 |
| Vibe19 image | `:latest` digest `sha256:6a4297b9…e6f54d` |
| Gate 0 | PUT kept `occupancy_schedule` |
| `diff_summary.json` | **405 blockers**, 2690 accepted, 3260 rows, `stop_rule_met=false` |

Prior cycle (`sha-8ab0b5e`): also **405** blockers. ECON SQL follow-on did not reduce the dump-vs-dump count.

## Four-rule soak (`sha-2c12c8e`)

| ID | pandas | SQL | Outcome |
| --- | ---: | ---: | --- |
| AHU-DUCTHI AHU_2 | 0.5 h FAULT | 1.83 h FAULT | Unchanged residual |
| ECON-2 AHU_1 | 0 h PASS | 1422.92 h FAULT | Still open (was 952.5 h; fan AND removed, damper still raw-class) |
| ECON-1 AHU_1 | 326 h FAULT | 0 h PASS | Still open |
| CHW-NOLOAD-1 CHILLER_2 | 524.5 h FAULT | SKIPPED_MISSING_ROLES | No false PASS |

## Measured blockers

| Artifact | Blockers |
| --- | ---: |
| `fdd_findings` | 217 |
| `sensor_diurnal_24h.csv` | 89 |
| `sensor_stats_fan_off.csv` | 74 |
| `sensor_stats_all.csv` | 21 |
| other | 4 |

Stop rule remains `blocker_count == 0`. Remaining FDD blockers are real FAULT/PASS and FAULT∩FAULT hours.

## Program B handoff

- PyPI **4.4.1** is on pypi.org (`dump_tables`, metric bins, vav_health).
- Windows Cursor: [`docs/agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md`](../agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md) for `vibe_code_apps_19`. bensbench does not edit playground; `docker pull ghcr.io/bbartling/vibe19:latest` only.

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-2c12c8e
./scripts/openfdd_stack_up.sh react-ot --no-pull
OPENFDD_ADMIN_PASSWORD=… python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```
