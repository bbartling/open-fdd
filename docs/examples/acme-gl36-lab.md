---
title: GL36 lab site (Acme)
parent: Examples & lab notes
nav_order: 1
---

# GL36 lab site (Acme)

{: .note }
> **Lab note only.** This documents a maintainer **example edge host** (site `acme`, building `vm-bbartling`) used for Guideline 36 supervisory FDD development. Replace inventory host names, IPs, and BACnet ranges for your site.

Reference for **ASHRAE Guideline 36** supervisory monitoring on a live lab edge. Rule code lives in `workspace/data/rules_py/`; commissioning uses **Arrow constants** (no `config.json`).

Trim & respond Niagara reference: [README_TRIM_RESPOND](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md).

## BACnet poll scope

Device filter (`infra/ansible/scripts/acme_trim_devices.sh`):

| Range | Equipment |
|-------|-----------|
| 1–100 | JCI VMA/VAV |
| 1100 | RTU-01 (AHU) |
| 1002 | Hot water plant |
| 11000–13000 | Trane UC210 VAV |

Poll interval: **60 s**. Commission from control machine:

```bash
cd infra/ansible
POLL_INTERVAL=60 ./scripts/acme_commission_gl36.sh
```

Points land in `edge_backup/local/acme/vm-bbartling/points.csv` for Ansible sync.

## Example FDD rules (Arrow)

### Duct static pressure high (AHU)

```python
"""AHU duct static high — GL36 trim advisory."""

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
"""AHU SAT too cold vs setpoint."""

import pyarrow.compute as pc

SAT_COLUMN = "sa-t"
SP_COLUMN = "sa-t-sp"
COLD_DELTA_F = 5.0


def apply_faults_arrow(table, cfg, context=None):
    sat = pc.cast(table[SAT_COLUMN], "float64")
    sp = pc.cast(table[SP_COLUMN], "float64")
    return pc.less(pc.subtract(sat, sp), -COLD_DELTA_F)
```

### Site rule stubs in the repo

| Rule file | Use |
|-----------|-----|
| `bench_stat_zn-t_flatline_1h.py` | Zone temp flatline — bind `ZN-T` per VAV |
| `acme_duct_static_flatline_1h_gl36_duct_t_r_input.py` | RTU duct static flatline |
| `oat_vs_web_spread_1h.py` | Local OAT vs OpenWeather JSON API |

### Local OA-T vs web weather (JSON API)

1. Control machine: `workspace/json_api.env.local` with `OPENWEATHER_API_KEY`
2. JSON API tab → **OpenWeatherMap** preset → **Register** (default poll **30 min**)
3. Bind BACnet local OAT in the model (`oa-t` historian column)
4. Enable `oat_vs_web_spread_1h.py` in Rule Lab — flags when `|oa-t − web-oat-t| > 8 °F`

## Deploy / upgrade (Ansible, this lab only)

```bash
cd infra/ansible
OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit <inventory_host> -e enable_bacnet_poll_driver=true
```

Full UI + image upgrade from control machine:

```bash
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_full.sh --limit <inventory_host>
infra/ansible/scripts/post_deploy_check.sh --limit <inventory_host> --full
```

Do **not** rsync dev `auth.env.local` to the edge (`deploy_sync_auth: false` in private host_vars). Regenerate credentials on the edge host if login fails after upgrade.

## AI-assisted data modeling (lab workflow)

1. BACnet poll running (~340 GL36 points @ 60 s on this lab host).
2. **Model & assignments** → export commissioning JSON for LLM-assisted binding.
3. Import returned JSON via commissioning import.
4. Pin FDD rules on `ZN-T`, `DA-T`, `duct-static`, `OAT`, etc. — export shows readable names in `fdd_rules_linked`.

Model seed: `workspace/data/acme_gl36_model.json`.
