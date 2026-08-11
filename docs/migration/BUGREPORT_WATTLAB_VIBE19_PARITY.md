# WattLab / Vibe19 parity — Building 100 (OpenFDD 4.3.0)

Oracle is **playground Vibe19** (`py-bacnet-stacks-playground/vibe_code_apps_19`) + live `open-fdd` 4.3.x (PR `#707`), **not** `tools/wattlab_export` and **not** `--skip-rules`.

A working copy also lives at `reports/wattlab-parity/BUGREPORT_WATTLAB_VIBE19_PARITY.md` (gitignored `/reports/`).

## Versions

| Side | Version / SHA |
| --- | --- |
| OpenFDD Python | **4.3.0** (not 3.0.1 / 4.2.0) |
| Python git | `0bb85fe` (occupied strings + hydronic ungate + lean `apply_normalized`) |
| PyPI 4.3.0 wheel catalog hash | `097eeda2282a17e785e70f1e9f941c554a8eeeb294ae581746d4d3c21b2e6072` |
| Live catalog hash (repo tree, `sql_rules/` visible) | `5acedd0ddc0bd91e0307539c4f029683197c995fdabb111412b760e74568d274` |
| Vibe19 app | playground PR `#86` |
| Rust central image | `ghcr.io/bbartling/openfdd-central:sha-2ce9c21` → health `3.3.0+2ce9c212a8b4` |
| Bundle schema | `openfdd_engineering_bundle_v1` (`legacy_schema_version`: `wattlab_dump_v3`) |
| Package | `/home/ben/raw_BUILDING_100_openfdd.zip` sha256 `5a8d9ff2…` |
| Gate 0 schedule | `fixtures/schedule_b100_7to5.json` (America/Chicago, 07:00–17:00 M–F) |

Wheel vs repo catalog hashes differ because `effective_catalog()` reads `sql_rules/registry.yaml` next to the repo root; a site-packages install does not ship that file. Both hashes are accepted by the Vibe19 pin.

## Before / after

| | Previous oracle | This run |
| --- | --- | --- |
| Oracle tree | `tools/wattlab_export` | playground `vibe_code_apps_19` |
| Rules | `--skip-rules` | `--run-all` → **2832** rows (48 × 59) |
| Schema | `wattlab_dump_v3` | `openfdd_engineering_bundle_v1` + legacy v3 |
| Zip | (skip-rules dump) | **7.7 MiB** (`vibe19_oracle_summary.zip`) |
| Timing | n/a (no rules) | rules **104.1 s** / analytics **9.2 s** / serialization **540.3 s** / zip **2.8 s** |
| Rust | `3.3.0+a2cca15` (1818 cached rows) | pulled `sha-2ce9c21`, `POST /api/fdd/run`, 1817 rows |
| Diff stop rule | met only because findings were deferred | **`blocker_count=0`** with rules on |

Serialization is still the long pole (shared telemetry + parquet + findings). Quality no longer triples frames; Building 100 fits in ~2.3 GiB RSS on an 8 GiB host (previous apply_normalized insert loop was OOM-killed).

## Status counts (pandas oracle)

| Status | Count |
| --- | ---: |
| NOT_APPLICABLE_EQUIPMENT_TYPE | 2108 |
| SKIPPED_EQUIPMENT_OFF | 210 |
| FAULT | 191 |
| SKIPPED_MISSING_ROLES | 180 |
| PASS | 143 |
| **Total** | **2832** |

Rust DataFusion: 1627 PASS / 168 FAULT / 22 SKIPPED_MISSING_ROLES (no N/A cartesian; extra SQL analytics ids).

## Intentional calculation changes (accepted, not blockers)

- **CHW-1**: missing hydronic proof → `SKIPPED_MISSING_ROLES`; zeros → `SKIPPED_EQUIPMENT_OFF`. SQL often omits the row or reports 0 h.
- **SCHED-247**: pressure is inferred runtime only; pandas PASS vs SQL FAULT on AHU duct static is 4.3.0 pressure-not-fault.
- **Occupied / unoccupied strings**: quality no longer marks them `NON_NUMERIC` (fixes SCHED-1 skip).
- **Hydronic missing proof**: `equipment_energized` continues instead of treating `missing_proof` as off (SV-RANGE / RCx on plants).
- **`parent_ahu`**: parser recognizes the Building 100 header; AHU_* is never mapped to tower `100`. Observed topology rows without a VAV folder are not `stale_map_ids`.
- **SQL `sql_screening`**: inventory is not at `mask_parity`. SQL runs all equipment types, lacks pandas skip/off gates, and uses `FC13-SAT-HIGH` as the FC13 alias. Rollup in `diff_summary.json` (`sql_screening_rollup`).

## Remaining OpenFDD work (not blockers this wave)

Numeric DataFusion hours still diverge on applicable FAULT∩FAULT pairs (AHU-DUCTHI, AHU-SATDEV, ECON-*, FC*) — confirm windows / fan gates. Next wave should promote selected rules from `sql_screening` → `mask_parity` in SQL, not by weakening Vibe19.

No PyPI **4.3.1** bump: pandas API is compatible; occupied-string + lean normalize ship in git/`master` after merge. Image SQL-only changes can ship without a wheel.

## Bundle / React / Rust readers

Accept **either**:

- `schema_version == openfdd_engineering_bundle_v1`, or
- `legacy_schema_version == wattlab_dump_v3` / `schema_version == wattlab_dump_v3`

New writes use `README.md` (still emit `README_WATTLAB.md` alias). `calibration_readiness.json` labels fuel + local TZ + geometry missing — do not treat `model_seed.json` as a calibrated EnergyPlus model.

## Runtime confirmation

```
open_fdd.__version__ == 4.3.0
```

Host 3.0.1 and Vibe19 `.venv` 4.2.0 are refused by `app.openfdd_runtime.require_supported_open_fdd()`.
