# WattLab / Vibe19 parity — Building 100 + Synthetic-59 (4.4.1 / `sha-8525cfc`)

Dump-vs-dump after playground **PR #92** (wheel 4.4.1, `dump_tables` in diagnostic/forensic bundles). OpenFDD is DataFusion JWT APIs on **`sha-8525cfc`** (PR **#729**). bensbench: pull only, `--no-pull` stack-up, no local docker/cargo release.

Working copy: `reports/wattlab-parity/` (gitignored).

## Cycle header

| Side | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD git/image | `8525cfc` / `ghcr.io/bbartling/openfdd-*:sha-8525cfc` |
| Central health | `3.3.0+8525cfca140f` |
| Vibe19 | `:latest` digest `sha256:101126ab…32760f07` |
| `open_fdd.__version__` | **4.4.1** catalog `2e684dbb…cba9` |
| Playground merge | PR **#92** `4b71061666d1c34c9c93b3c66fa08e043ae856ae` |
| Gate 0 | PUT kept `occupancy_schedule` |
| `diff_summary.json` | **449 blockers**, 2689 accepted, 3303 rows, `stop_rule_met=false` |

## Synthetic-59

vibe19 **59/59**, OpenFDD SQL **59/59**, analytics soak PASS. Planted faults are 1.0 h. Synth ECON damper is 0–1, not B100 0–100.

## Four-rule B100 soak

| ID | pandas | SQL | Outcome |
| --- | ---: | ---: | --- |
| AHU-DUCTHI AHU_2 | 0.5 h FAULT | 1.83 h FAULT | residual |
| ECON-2 AHU_1 | 0 h PASS | 1422.92 h FAULT | still open after inline CASE |
| ECON-1 AHU_1 | 326.08 h FAULT | 0 h PASS | still open |
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

Oracle dump now writes vav/mech/motor CSVs. Per-row vav_health score gaps are real blockers, not a missing-file skip.

Prompt 2 is **closed** — see [`VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md`](../agent/VIBE19_PROMPT2_VAV_HEALTH_EXPORT.md).
