---
title: Acme GL36 FDD (vm-bbartling)
parent: Operations
nav_order: 6
---

# Acme GL36 FDD (vm-bbartling)

Doc-only reference for **ASHRAE Guideline 36** supervisory monitoring on the Acme edge (`acme` / `vm-bbartling`). Rule code lives in `workspace/data/rules_py/`; commissioning uses **Arrow constants** (no `config.json`).

Trim & respond Niagara reference: [README_TRIM_RESPOND](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md).

## BACnet poll scope

Device filter (`infra/ansible/scripts/acme_trim_devices.sh`):

| Range | Equipment |
|-------|-----------|
| 1–100 | JCI VMA/VAV |
| 1100 | RTU-01 (AHU) |
| 1002 | Hot water plant |
| 11000–13000 | Trane UC210 VAV |

Poll interval: **60 s**. Commission: `POLL_INTERVAL=60 ./infra/ansible/scripts/acme_commission_gl36.sh` → `edge_backup/local/acme/vm-bbartling/points.csv`.

## Example FDD rules (Arrow constants)

### Duct static pressure high (AHU)

```python
"""Acme AHU duct static high — GL36 trim advisory."""

import pyarrow.compute as pc

VALUE_COLUMN = "duct-static"
HIGH_INWC = 1.20
LOOKBACK_HOURS = 3


def _kit_lookback_stats(table, *, hours=None):
    h = hours if hours is not None else LOOKBACK_HOURS
    ts = pc.cast(table["timestamp"], "timestamp[us, UTC]")
    tmin, tmax = pc.min(ts).as_py(), pc.max(ts).as_py()
    span_h = (tmax - tmin).total_seconds() / 3600.0 if tmin and tmax else 0.0
    print(f"lookback={h}h rows={table.num_rows} start={tmin} stop={tmax} span={span_h:.2f}h")


def apply_faults_arrow(table, cfg, context=None):
    _kit_lookback_stats(table)
    return pc.greater(pc.cast(table[VALUE_COLUMN], "float64"), HIGH_INWC)
```

### SAT too cold vs setpoint

```python
"""Acme AHU SAT too cold vs setpoint."""

import pyarrow.compute as pc

SAT_COLUMN = "sa-t"
SP_COLUMN = "sa-t-sp"
COLD_DELTA_F = 5.0


def apply_faults_arrow(table, cfg, context=None):
    sat = pc.cast(table[SAT_COLUMN], "float64")
    sp = pc.cast(table[SP_COLUMN], "float64")
    return pc.less(pc.subtract(sat, sp), -COLD_DELTA_F)
```

### Zone temp flatline (existing site rule)

See `workspace/data/rules_py/bench_stat_zn-t_flatline_1h.py` — bind `ZN-T` per VAV in Model & assignments.

### Duct static flatline (site rule stub)

See `workspace/data/rules_py/acme_duct_static_flatline_1h_gl36_duct_t_r_input.py` — tune `VALUE_COLUMN` to historian column for RTU duct static.

### Local OA-T vs web weather (JSON API)

Cross-check a drifting outdoor-air sensor against [OpenWeatherMap](https://openweathermap.org/api) via the generic JSON API driver:

1. Control machine: `workspace/json_api.env.local` with `OPENWEATHER_API_KEY` — synced on deploy (`deploy_sync_json_api_env`).
2. JSON API tab → **Register OpenWeather bundle** (poll **20 min** — `web-oat-t`, `web-rh`, `web-weather-desc`).
3. Bind BACnet **local OAT** in the model: **Tracer SC** device `10000` → `Facility Outdoor Air Temperature` (`fdd_input` **OAT**, historian `oa-t`). Hot-water plant `1002` has no outdoor-air point.
4. Enable rule `workspace/data/rules_py/oat_vs_web_spread_1h.py` in Rule Lab — flags when `|oa-t − web-oat-t| > 8 °F`.

Scheduled FDD merges BACnet and `json_api` historian columns by nearest timestamp (30 min tolerance).

## Deploy / upgrade (GHCR only)

```bash
cd infra/ansible
POLL_INTERVAL=60 ./scripts/acme_commission_gl36.sh
OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
```

Do **not** rsync dev `auth.env.local` to the edge (`deploy_sync_auth: false` in `host_vars/acme_vm_bbartling.yml`). Regenerate on-host if the bridge rejects example credentials.

## AI-assisted data modeling

1. BACnet poll running (340+ GL36 points @ 60 s).
2. **Model & assignments** → copy prompt + commissioning JSON for LLM.
3. Import returned JSON via commissioning import.
4. Pin `fdd_rule_ids` on `ZN-T`, `DA-T`, `duct-static`, `OAT`, etc.

Model seed: `workspace/data/acme_gl36_model.json`.
