# WattLab / Vibe19 parity — Building 100 + Synthetic-59 (4.4.1 / `sha-5aebdfc`)

Dump-vs-dump after playground **PR #92** (wheel 4.4.1, `dump_tables` in diagnostic/forensic bundles). OpenFDD is DataFusion JWT APIs on **`sha-5aebdfc`** (PR **#731** CAST / `>= 1.5`). bensbench: pull only, `--no-pull` stack-up, no local docker/cargo release.

Working copy: `reports/wattlab-parity/` (gitignored).

## Cycle header

| Side | Value |
| --- | --- |
| Date | 2026-08-16 |
| OpenFDD git/image | `5aebdfc` / `ghcr.io/bbartling/openfdd-*:sha-5aebdfc` |
| Central health | `3.3.0+5aebdfc54434` |
| Vibe19 | `:latest` digest `sha256:101126ab…32760f07` |
| `open_fdd.__version__` | **4.4.1** catalog `2e684dbb…cba9` |
| Playground merge | PR **#92** `4b71061666d1c34c9c93b3c66fa08e043ae856ae` |
| Gate 0 | PUT kept `occupancy_schedule` |
| `diff_summary.json` | **449 blockers**, 2689 accepted, 3303 rows, `stop_rule_met=false` |

## Synthetic-59

OpenFDD SQL **59/59** on `sha-5aebdfc`. Planted faults are 1.0 h. Synth ECON damper is 0–1. GHA percent fixtures (damper 20) pass; they are not B100 historian (damper ~100 when OAT > 63 °F).

## Four-rule B100 soak

| ID | pandas | SQL | Outcome |
| --- | ---: | ---: | --- |
| AHU-DUCTHI AHU_2 | 0.5 h FAULT | 1.83 h FAULT | residual |
| ECON-2 AHU_1 | 0 h PASS | 1422.92 h FAULT | CAST live; parquet Float64 0–100, high-OAT median 100. Not a type bug. |
| ECON-1 AHU_1 | 326.08 h FAULT | 0 h PASS | SQL damper not stuck closed |
| CHW-NOLOAD-1 CHILLER_2 | 524.5 h FAULT | SKIPPED_MISSING_ROLES | no false PASS |

## Measured blockers

| Artifact | Blockers |
| --- | ---: |
| `fdd_findings` | 217 |
| `sensor_diurnal_24h.csv` | 89 |
| `sensor_stats_fan_off.csv` | 74 |
| `vav_health_matrix.csv` | 44 |
| `sensor_stats_all.csv` | 21 |
| other | 4 |

Prompt 2 is **closed** — see [`VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md`](../agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md).
