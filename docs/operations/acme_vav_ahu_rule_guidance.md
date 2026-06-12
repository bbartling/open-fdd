---
title: Acme VAV/AHU rule guidance
parent: Operations
nav_order: 10
---

# Acme VAV/AHU FDD rule bundle

Practical Arrow-native rule set for **acme** (`vm-bbartling`): one RTU/AHU (`acme-vm-bbartling-rtu-01`, BACnet **1100**) feeding **JCI VAVs** (instances 1–100, imperial °F at wire) and **Trane VAVs** (11000–13000, metric °C converted to °F before feather via `device_poll_profiles.csv`).

Install / refresh rules:

```bash
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling \
  --ahu-equipment-id acme-vm-bbartling-rtu-01 --fan-point-id 1100-analog-output-1
```

Validate bundle locally:

```bash
python3 scripts/acme_validate_fdd_bundle.py
```

## Mixed manufacturers and units

| Manufacturer | BACnet instances | Wire units | Open-FDD handling |
|--------------|------------------|------------|-------------------|
| JCI VAV | 1–100 | °F | Rules use `temp_unit: imperial`; no poll conversion |
| Trane VAV | 11000–13000 | °C | `metric_temp_f` in `edge_config/acme/vm-bbartling/device_poll_profiles.csv` converts to °F before feather |
| RTU AHU | 1100 | °F | AHU rules bind to equipment / fan point |

All zone-temperature rules share **imperial bounds** after poll conversion. If a new Trane box is added without a profile row, zone OOB/flatline will be wrong until the profile is added and data re-ingested.

Command scaling (damper, reheat, fan): rules normalize **0–1 vs 0–100%** with `pc.if_else(greater(c, 1.0), divide(c, 100), c)`.

Poll interval: Acme BACnet poll loop is **60 s**. Flatline windows use `poll_interval_s: 60` and `flatline_minutes: 60` → **60 samples per hour**, not the legacy 5-min × 12 assumption.

## Rule matrix

| Phase | Priority | Rule ID (prefix `acme-`) | Module | Fault | Equipment | Required points | Optional | Gating | Technician meaning | False-positive risks |
|-------|----------|--------------------------|--------|-------|-----------|-----------------|----------|--------|--------------------|--------------------|
| 0 | 1 | `oat-bounds` | `oat_sensor_bounds.py` | BLD-B | Building | OAT | — | — | OAT sensor stuck high/low | Extreme weather; sensor in sun/wind |
| 0 | 2 | `oat-flatline-1h` | `oat_sensor_flatline.py` | BLD-B | Building | OAT | — | 1 h @ 60 s poll | OAT not updating | Equipment powered off (rare for OAT) |
| 0 | 3 | `oat-spike` | `oat_sensor_spike.py` | BLD-B | Building | OAT | — | **Disabled** — enable after spike tuning | Bad OAT spike | Fast legitimate weather fronts |
| 0 | 3b | `oat-vs-web-spread` | `oat_vs_web_spread_1h.py` | BLD-B | Building | `oa-t` + `web-oat-t` | OpenWeather JSON API | Enabled when both columns present | Local OAT diverges from weather | Microclimate; wrong city in `OPENWEATHER_CITY` |
| 0 | 4 | `zn-t-oob-occupied` | `vav_zone_temp_bounds_occupied.py` | VAV-C | VAV | ZN-T | schedule | Occupied 8–17 | Zone too hot/cold when occupied | Wide default bounds (65–78 °F); tune per site |
| 0 | 5 | `zn-t-flatline-1h` | `vav_zone_temp_flatline_occupied.py` | VAV-C | VAV | ZN-T | schedule | Occupied + 1 h flatline | Zone sensor failed | Long steady occupied periods |
| 0 | 6 | `da-t-flatline-1h` | `flatline_1h.py` | VAV-E | VAV | DA-T | — | 1 h flatline | DAT sensor stuck | Box off / no airflow |
| 0 | 7 | `sat-flatline-1h` | `flatline_1h.py` | AHU-C | AHU | SAT | — | 1 h flatline | SAT sensor stuck | Fan off |
| 0 | 8 | `sap-flatline-1h` | `flatline_1h.py` | AHU-F | AHU | Duct static | — | 1 h flatline | Static sensor stuck | Fan off |
| 1 | 9 | `vav-damper-stuck` | `vav_damper_stuck_flatline.py` | VAV-D | VAV | Damper cmd | Damper status | Open ≥97.5% + flat 1 h | Damper stuck open | Constant max cooling call |
| 1 | 10 | `vav-airflow-low` | `vav_airflow_low.py` | VAV-D | VAV | SA-F, damper cmd | SAFLOW-SP | Damper open + low flow | Low airflow / static / pickup | Low minimum set during test |
| 1 | 11 | `vav-reheat-warm-ambient` | `zone_reheat_warm_ambient.py` | VAV-A | VAV | Reheat cmd, OAT on frame | occupied | **Disabled** — enable when HW season stable | Reheat on when OAT warm | Morning warmup; missing OAT column |
| 1 | 12 | `vav-reheat-leak` | `vav_reheat_dat_vs_sat.py` | VAV-A | VAV | DA-T, AHU SAT on frame | — | **Disabled** — needs SAT in feather | Reheat leak / hot DAT | Missing `sa-t` on wide frame |
| 2 | 13 | `ahu-afterhours-runtime` | `ahu_afterhours_runtime.py` | BLD-C | AHU | Fan cmd/status | Zone avg cols | Unoccupied + fan on + zones OK | Fan running after hours | Night setback / cleanup |
| 2 | 14 | `mat-oob-economizer` | `oob_rolling.py` | AHU-D | AHU | MAT | OAT/RAT/fan | **Disabled** — validate economizer points first | MAT sensor / mixing fault | Startup transients |
| 2 | 15 | `ahu-run-hours` | `ahu_run_hours.py` | — | AHU | Fan cmd | compressors | Script (analytics) | Run-hour rollup | Missing fan column → empty metrics |
| — | — | Stale telemetry | Poll health dashboard | BLD-D | All | timestamp + poll interval | — | Not an edge rule | Point not updating | Use poll health, not FDD sweep |

### Phase 2+ (not enabled by default)

Enable only after point coverage on RTU **1100** is verified (OAT, MAT, RAT, SAT, OA damper, cooling cmd):

- **AHU-A** duct static not maintained — needs static SP + fan speed (future rule)
- **AHU-D** mixed air envelope — `mixing_envelope_mask` + fan on
- **AHU-E** economizer trio — 100% OA tracking, mech cooling when free cooling available, OA damper excess open

### Phase 3 rollups (future)

- Many simultaneous **VAV-D** airflow-low → suggest AHU static / fan issue
- Many **VAV-B/C** comfort faults → AHU scheduling or SAT problem
- Hot-water plant support when HW supply temp is modeled

## Data model checks

Before enabling more rules:

1. **No duplicate BACnet device instances** on equipment rows (poll health merges by `bacnet_device_id`).
2. **No duplicate `point_id`** rows with different `external_id` / fdd aliases (causes historian_lag double-count).
3. **Trane devices** in `device_poll_profiles.csv` with `metric_temp_f`.
4. Run `scripts/acme_validate_fdd_bundle.py` after model edits.

## Tuning notes

- **`acme-zn-t-oob-occupied`**: if flag rate &gt; ~70%, use tuning brief / bounds auto-tune (needs ≥85% flagged + analytics on Arrow sweep).
- Disable noisy rules via `enabled: false` in `setup_gl36_fdd.py` rather than deleting modules.
- Economizer and reheat-leak rules stay off until OAT/MAT/SAT columns are confirmed on the 7-day feather window.

## JSON API weather + BACnet OAT

- OpenWeather registered on edge JSON API tab (`web-oat-t`, `web-rh`, ~20–30 min poll).
- Local OAT: bind **`1100-unknown-2`** (RTU outdoor air local) with `external_id: oa-t` — `scripts/acme_patch_oat_column.py`.
- Rule `acme-oat-vs-web-spread` flags when local vs web spread exceeds 8 °F.

## BACnet override scans

Commission agent rotates **one device/hour** through P8 priority-array reads. Status: `GET /api/bacnet/overrides/status`. See [Operator override scans]({{ "/bacnet/override-scans/" | relative_url }}).

## Docker backup / recovery

Edge upgrades via `scripts/upgrade_edge_ghcr.sh` preserve `workspace/data` and feather volumes on the VM. After upgrade:

1. `curl /health` → expect matching `openfdd_version`
2. `./infra/ansible/scripts/acme_operational_verify.sh`
3. Re-push rules if `rules_store.json` was reset: `setup_gl36_fdd.py --host … --token …`

Feather backup: snapshot `workspace/data/feather/` (or site pack export) before major model changes.
