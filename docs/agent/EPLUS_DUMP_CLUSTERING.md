---
title: E+ dump and clustering export
parent: External agents
nav_order: 21
---

# E+ dump and clustering export

User-facing name for engineering bundle export + offline pandas clustering (legacy paths still say “WattLab” in Rust API routes).

## Online dump (central)

[`scripts/agent_eplus_dump.sh`](../../scripts/agent_eplus_dump.sh) (shim: `agent_wattlab_dump.sh`):

1. Import package → create job → `POST /api/jobs/{id}/wattlab/dumps` (API rename to `/eplus/dumps` is follow-up)
2. Download zip
3. Chain [`scripts/eplus_dump_clustering_export.py`](../../scripts/eplus_dump_clustering_export.py)

## Offline clustering (pandas / sklearn)

```bash
python3 scripts/eplus_dump_clustering_export.py \
  --building-root /path/to/BUILDING_50 \
  --building-id BUILDING_50
```

Outputs under `reports/eplus-dump/artifacts/<building_id>/clustering/`:

| File | Use |
|------|-----|
| `clustering_features.csv` | Wide stats per equipment×role — KMeans / PCA |
| `clustering_timeseries_long.parquet` | Long historian melt |
| `README_clustering.md` | Copy-paste sklearn example |
| `MANIFEST.json` | Schema `eplus_clustering_v1` |

Artifact root: `EPLUS_DUMP_ROOT` (default `reports/eplus-dump/`). Legacy `reports/wattlab-parity/` still works via [`scripts/eplus_paths.py`](../../scripts/eplus_paths.py).

## Agent spec

- Dump engine: `tools/wattlab_export/` (offline; central shells when `OPENFDD_WATTLAB_PYTHON_EXPORT=1`)
- Compare helpers (tests): `scripts/eplus_parity_compare.py`
- Retired vibe19 dual-parity: `scripts/retired/vibe19-parity/`
