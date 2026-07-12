# Cookbook → SQL rule mapping

Cross-reference between Open-FDD **online expression cookbook** (`docs/rules/cookbook/`) and the **shipped DataFusion SQL registry** (`sql_rules/registry.yaml`).

**Counts (file-backed, 2026-07-12):**

| Slice | Count |
|-------|------:|
| Canonical OG50 (issue #482) | 50 |
| PID-HUNT-1 (additive #51) | 1 |
| Analytics rollups (not OG50) | 4 |
| **Registry total** | **55** |

Proven on BUILDING_100 @ 0.5h tolerance where noted (see `docs/benchmarks/RUST_DATAFUSION_PARITY_BENCHMARK.md`).
Newer OG50 ports are `parity_status: cookbook_defined` until BUILDING_100 / synthetic fixtures prove them.

| Cookbook / rule ID | SQL rule_id | SQL file | Confirm (s) | Parity | Notes |
| --- | --- | --- | ---: | --- | --- |
| VAV-1 | VAV-1 | vav1_comfort_fault.sql | 900 | proven | |
| OAT-METEO | OAT-METEO | oat_meteo_fault.sql | 900 | proven | |
| FC13 SAT high | FC13-SAT-HIGH | sat_high_fault.sql | 600 | proven | |
| ECON-2 | ECON-2 | economizer_fault.sql | 300 | proven | |
| FC1–FC3, FC7–FC12 | FC1… | fc*.sql | 300–600 | proven / skip | FC7 may skip missing htg_valve |
| ECON-1 / ECON-4 | ECON-1 / ECON-4 | econ*.sql | 600 | proven | |
| ECON-3 / ECON-5 | ECON-3 / ECON-5 | econ3_*.sql / econ5_*.sql | 600 | cookbook | Newly ported |
| SV-RANGE…SV-4 | SV-* | sv_*.sql | 300 | cookbook | Sweep approximations |
| FC4–FC6, FC14–FC15 | FC* | fc*.sql | 600–3600 | cookbook | |
| AHU-SATDEV / DUCTHI / SIMUL | AHU-* | ahu_*.sql | 300–600 | cookbook | |
| OA-1 / DMP-1 / VLV-1 | OA-1 / DMP-1 / VLV-1 | *.sql | 300–600 | cookbook | |
| VAV-3/4/5/7 / REHEAT-STUCK | VAV-* | vav*.sql | 300–600 | cookbook | |
| CHW-1…4 / HP-1 | CHW-* / HP-1 | *.sql | 300–900 | cookbook | Synthetic fixtures preferred |
| WX-1 / WX-2 | WX-* | wx*.sql | 300 | cookbook | |
| TRIM-1/3/4 | TRIM-* | trim*.sql | 1800 | cookbook | Advisories |
| SCHED-1 / CMD-1 | SCHED-1 / CMD-1 | *.sql | 300–1800 | cookbook | ALWAYS gates |
| FAN / zone analytics | FAN-RUNTIME-HOURS… | *.sql | 0 | proven | Not counted in OG50 |
| **PID-HUNT-1** | **PID-HUNT-1** | **pid_hunt_1.sql** | 0 | cookbook | **51st**; distinct from FC4/CTRL-2 |

Full inventory: [ISSUE_482_RULE_INVENTORY.md](../migration/vibe19/ISSUE_482_RULE_INVENTORY.md).

**Python oracle:** `tools/python_oracle/export_pandas_oracle.py` (optional; not a production runtime dependency on Vibe19).

**Operational gates / statuses:** [operational-gates.md](../rules/cookbook/operational-gates.md) — `mode` + `predicate` (not conflated `type`), six-status contract.

**Maintainer rule:** expression cookbooks under `docs/rules/cookbook/` are **never reduced**. Add rules/gates/SQL mappings; do not delete FC4, CTRL-2, or other existing sections.
