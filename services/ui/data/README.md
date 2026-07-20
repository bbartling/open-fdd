# External HVAC data

Do **not** copy full site CSV exports into this repo (often hundreds of MB to multi‑GB).

## Preferred inputs

| Mode | What to use |
| --- | --- |
| Demo / Cloud / Docker | `openfdd_package_v1` **zip** (browser upload ≤ 500 MB) |
| Agent / large sites | Path load or `agent_afdd.py` (package safety default **2048 MB**) |
| Native local folder | Historian tree on disk (not committed) |

Configure a machine-local root if needed:

| Role | Example |
| --- | --- |
| Import root | `/path/to/hvac_systems_CLEANED` |
| Optional staging | `vibe_code_apps_19/data/hvac_systems_CLEANED/` (gitignored) |

Set via `../data_paths.local.yaml` or `HVAC_DATA_ROOT` — see [`data_paths.example.yaml`](../data_paths.example.yaml).

Typical tree (when using folders):

```
hvac_systems_CLEANED/
  weather/history_wide.csv
  BUILDING_100/manifest.json
  BUILDING_100/AHU_*/history_wide.csv
  BUILDING_100/VAV/<terminal_id>/columns.csv
  BUILDING_50/...
```

Package layout and size limits: [`docs/PACKAGE_SPEC.md`](../docs/PACKAGE_SPEC.md), [`docs/DOCKER.md`](../docs/DOCKER.md).
