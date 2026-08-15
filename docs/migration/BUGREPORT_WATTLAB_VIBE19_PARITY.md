# WattLab / Vibe19 parity — Building 100 (OpenFDD 4.4.0)

New dump-vs-dump cycle 2026-08-15. Oracle is GHCR vibe19 `docker exec scripts/agent_afdd.py` (not `tools/wattlab_export`). OpenFDD is DataFusion JWT APIs (`wattlab_parity_ofdd_rust_bundle.py`).

Working copy: `reports/wattlab-parity/` (gitignored artifacts).

## Cycle header

| Side | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD git | `9e280ae` |
| OpenFDD image | `ghcr.io/bbartling/openfdd-*:sha-9e280ae` |
| Central health | `3.3.0+9e280ae294b0` |
| `/api/fdd/rules` | **66** (62 pandas + 4 SQL analytics) |
| PyPI / vibe19 wheel | **4.4.0** catalog hash `2e684dbb8f3188f06942c3cb0155aef4149713e7244b9f7733262f182465cba9` |
| Vibe19 image | `:latest` == `:develop` digest `sha256:6a4297b9d461befdba19891a087e6a4ef26af345aff0e5b1274756f528e6f54d` rev `8ca6a3b` |
| Package | `/home/ben/raw_BUILDING_100_openfdd.zip` sha256 `5a8d9ff2…` |
| Gate 0 | PUT kept `occupancy_schedule` (no disk restore) |
| Mech cooling | `web_oa_t` peak **70–75 / 204.58 h**, total **1156.5** |
| VAV Health (OpenFDD after FDD) | `1/3`: 22, `2/3`: 19, `?/3`: 2 (not all unknown) |
| `diff_summary.json` | **2596 blockers**, 63 accepted, 4233 rows, `stop_rule_met=false` |

VAV Health is an analytic, not a 63rd diagnostic.

## Measured blockers (honest)

Primary families from `diff_matrix.csv` (`severity=blocker`):

| Artifact | Blockers | Notes |
| --- | --- | --- |
| `fdd_findings` | 1429 | See pairs below |
| sensor_* tables | ~1037 | hour/row schema seams vs pandas dump |
| `motor_weekly` / `motor_hours` | 83 | |
| RCx / schedule inference | 47 | |

FDD status pairs (oracle → OpenFDD):

| vibe19 | ofdd | n |
| --- | --- | --- |
| `NOT_APPLICABLE_EQUIPMENT_TYPE` | *(row omitted)* | 750 |
| `SKIPPED_EQUIPMENT_OFF` | `PASS` | 174 |
| `SKIPPED_MISSING_ROLES` | `PASS` | 118 |
| `SKIPPED_MISSING_ROLES` | omitted | 112 |
| `FAULT` ∩ `FAULT` hour gap | | 97 |
| `FAULT` vs `PASS` | | 66 |
| `PASS` vs `FAULT` | | 51 |
| skip vs `FAULT` | | 56 |

SQL omitted N/A rows (863) is the largest FDD class: vibe19 emits N/A per equipment; Rust omits the row. Product follow-on: emit `NOT_APPLICABLE_EQUIPMENT_TYPE` for every (rule, equipment) in the vibe19 universe **or** drop N/A from the oracle dump before compare.

FAULT∩FAULT hour deltas remain **blockers** (not accepted). Highest-count rules in the FDD blocker set include AHU-SIMUL, CHW-2/3/4, CW-*, ECON-3/5/7, FC5/6/7, OAT-METEO, SV-RATE (48 equipment each — mostly N/A omit).

## Accepted / consumer lag

- `vav_health_matrix.csv` missing from vibe19 **diagnostic** dump even though the image wheel is **4.4.0** and `open_fdd.analytics.vav_health` imports. OpenFDD bundle wrote the matrix. Prompt 2 (Streamlit/WattLab export) still needed on the vibe19 repo — not an OpenFDD SQL bug.
- Rust extra `weather`/`unknown` equipment vs pandas 48-equip universe.
- Bundle `topology.csv` empty (`missing_table:topology.csv`) — assembler gap, filed as missing_apis on capture.
- Oracle quality flags / setpoints calendar medians without a matching Rust route (pre-existing product gaps).

## Not done this cycle

- No greenwash of `expected_faults.csv`.
- No FC7 parity promotion (needs executable fixtures, not this B100 matrix).
- No Windows Prompt 2 edits.

## Commands used

```bash
docker pull ghcr.io/bbartling/openfdd-central:sha-9e280ae  # + web/mqtt/fieldbus
docker pull ghcr.io/bbartling/vibe19:latest
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/wattlab_parity_oracle_dump.py
OPENFDD_ADMIN_PASSWORD=… python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```
