---
title: Vibe20 / WattLab integration matrix
parent: Migration
nav_order: 3
---

# Vibe20 / WattLab ↔ Open-FDD integration matrix

**Open-FDD tip:** `sha-d631e9c` · **vibe20 reference:** playground `vibe_code_apps_20` / `wattlab/` on `develop`.

Open-FDD does **not** run EnergyPlus in-process. It produces engineering evidence,
job-native WattLab handoffs, and optional zip dumps; vibe20 / an approved external
runner consumes them. Central may **queue** E+ run metadata
(`POST /api/jobs/{id}/eplus/runs` → `wattlab/runs/*.json`) and attach artifact
hashes — never a Docker socket.

| Capability | vibe20 consumer | Open-FDD producer today | Job-native target | Status |
|------------|-----------------|-------------------------|-------------------|--------|
| Equipment inventory | seed / studio | package + data model | `job/mapping/` + inventory JSON | PARTIAL |
| Role map | seed | session / package | `job/mapping/role_map.json` | PARTIAL |
| Dataset window | seed | package report / frames | `job.json` window + dataset_revision | PARTIAL |
| Schedules | seed / model | `model_seed.infer_schedules` | Persist under job configs | PARTIAL |
| Setpoints | seed | `wattlab_dump.setpoints_table` | DF query → artifact | PARTIAL |
| Sensor statistics | seed | `sensor_stats_tables` (pandas) | analytics_sql | PARTIAL |
| Weather provenance | weather / EPW | BAS vs web helpers + dump | Explicit source tags in artifacts | PARTIAL |
| Operating signatures | seed | `model_seed.operating_signatures` | Persist + DF profiles | PARTIAL |
| 24h / weekday profiles | seed | `diurnal_profiles` (pandas) | DF | PARTIAL |
| FDD results | seed findings | registry results + `fdd_findings.csv` | `job/runs/` + `job/findings/` | DONE |
| Mech cooling evidence | honesty rules | analytics / dump | Documented hierarchy; DF later | PARTIAL |
| Utility bills / Fuel campus | vibe20 Fuel Excel+campus | `POST /api/fuel/campus/import` + `/api/analytics/fuel` (Rust) | `workspace/data/fuel/<campus_id>/` | PARTIAL (Phase A Fuel) |
| Model assumptions | studio | gaps in dump README | `assumptions.json` + NEEDS_INPUT | MISSING |
| WattLab handoff | seed / bundle | zip + job-native JSON | `job/wattlab/handoffs/` (SoT) | DONE |
| EnergyPlus IDF / sim | `wattlab/energyplus/` | queue metadata only | Out of process; hashes/status on job | PARTIAL (D4 stub) |
| ECM / finance | ecm / finance | — | External; link results under job | N/A (external) |
| Calibration history | calibrate* | — | `job/wattlab/calibration/` metadata | MISSING |
| Dump zip v3 | `wattlab/seed/bundle.py` | `wattlab_dump` Export | Additive; SoT is job-native handoff | DONE |

## Honesty rules (keep)

- Never invent building type, floor area, city, lat/lon, capacity, or utility bills.
- Missing inputs stay visible as `NEEDS_INPUT` (or equivalent).
- Detection ≠ engineering finding; findings need review disposition once PR7 lands.
- Chilled-water pump runtime alone does **not** prove compressor operation.

## Anti-pattern to retire

```text
Open-FDD → giant CSV → reload everything in pandas in vibe20 → rediscover
```

Target: Job is canonical; WattLab seed reads job artifacts / handoff without recomputing the whole telemetry model.
