# Data modeling — packages, utilities, export bundles

Use when ingesting campus data, wiring utility analytics, or building ML-ready exports.

## Package layout (`openfdd_package_v1`)

Authoritative ingest: [`edge/src/csv_ingest/package.rs`](../../../edge/src/csv_ingest/package.rs).

```
<building_id>/
  manifest.json              # schema_version: openfdd_package_v1
  session_config.json        # optional
  <equipment_id>/
    history_wide.csv
    history_wide.json        # equipType + points { role → column }
  utilities/                 # optional utilities_v1
    manifest.json
    electric/
      monthly_bills.csv
      utility_interval_15m.csv   # optional
      bas_submeter_interval.csv  # optional
    gas/
      monthly_bills.csv
```

**Nested wrappers:** manifests may sit several folders deep (e.g. Creekside). Ingest walks for a unique `openfdd_package_v1` manifest (depth ≤ 8).

**Wrapper utilities:** `utility_bills_monthly.csv` beside the nested package folder maps to `utilities/electric/monthly_bills.csv`.

## Equipment typing

- Stamp `equipType` / `equipment_type` in package maps. That stamp is the classifier (agent rule 64, [#1043](https://github.com/bbartling/open-fdd/issues/1043)).
- Opaque ids are valid when stamped (`AC_1` + `equipType: ahu` is an AHU). A missing or unrecognized stamp is unclassified for plots, RCx cohorts, overview families, weather selection, motor groups, VAV health, and rule applicability. Do not infer kind from `equipment_id`.
- The framework never hardcodes one building. `building_id` is a parameter (package, JWT, request, or env). Tests and lab fixtures may name a site; product defaults must not (rule 62).
- Never prefer a fixture id (`AHU_1`, `RTU_01`, `VAV_1`) over the stamp. A missing or unrecognized stamp matches nothing.
- Never substring, prefix, `LIKE`, `ILIKE`, `contains`, or `starts_with` on `equipment_id`. Prefix match is the plot-filter defect: `RTU_01` must not select `RTU_010`. Preset tokens name canonical kinds. Selection is the stamp, then exact `equipment_id` equality. An exact id is allowed only after the type filter. Id text cannot add or remove equipment that has a stamp.
- Do not invent an MQTT delta payload. MQTT historian uses the same package data model; topic text is not an equipment kind.
- Parent-AHU id proposals are link suggestions, not cohort membership and not a plot filter.
- **ZONE** = FCU (`fcu`, valve PID) or standalone DDC (`zone_other`) — comfort + zone sensor FDD. **UV** = CV AHU (`unitVentilator`). See [`docs/modeling/zone-terminals.md`](../../../docs/modeling/zone-terminals.md).
- Meters: `equipType: meter` with roles `kwh`, `electric_kw` for `SV-*` and `UTIL-*` rules.

## Utility FDD rules

| Rule | Compare |
|------|---------|
| `UTIL-MONTHLY` | BAS monthly kWh sum vs `utility_monthly.kwh` |
| `UTIL-INTERVAL` | BAS 15m vs `utility_interval` (MAE threshold) |
| `SV-*` | Sensor validation on meter roles (`kwh`, `electric_kw`) |

SQL: `sql_rules/util_monthly_fault.sql`, `util_interval_fault.sql`. Registry: `sql_rules/registry.yaml`.

## Engineering & ML export (`openfdd_engineering_bundle_v1`)

Rust-first: `POST /api/jobs/{job_id}/exports` (profiles: summary, diagnostic, forensic).

Key paths in ZIP:

- `MANIFEST.json`, `README.md`
- `catalog/equipment.json`, `catalog/feature_catalog.json`
- `labels/label_catalog.json`
- `splits/chronological_splits.json`
- `summaries/utility_monthly_electric.csv` when utilities present
- `data/package_snapshot/` (diagnostic/forensic)

Offline validator: `scripts/openfdd_bundle_validate.py validate <bundle.zip>`

Deprecated alias: `POST /api/jobs/{job_id}/wattlab/dumps`

## Pandas quick joins

```python
import pandas as pd
hist = pd.read_parquet("data/telemetry/AHU_1.parquet")  # when present in bundle
bills = pd.read_csv("summaries/utility_monthly_electric.csv")
```

## Legacy fuel campus ZIP

Read-only: `services/central/src/fuel/import.rs` — do not use for new sites; import utilities via package.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) — Haystack to SQL roles
- [`openfdd-rcx-fdd-plot-poll`](../openfdd-rcx-fdd-plot-poll/SKILL.md) — blank charts after a bad map
- [`openfdd-typst-rcx-report`](../openfdd-typst-rcx-report/SKILL.md) — report figures from mapped roles
- [`openfdd-sql-fdd`](../openfdd-sql-fdd/SKILL.md) — rule SQL
