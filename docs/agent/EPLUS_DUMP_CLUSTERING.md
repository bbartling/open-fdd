---
title: E+ dump and clustering export
parent: External agents
nav_order: 21
---

# E+ dump and clustering export

User-facing name for **Engineering & ML bundle** export + offline pandas clustering.

## Online export (central — Rust-first)

[`scripts/agent_eplus_dump.sh`](../../scripts/agent_eplus_dump.sh):

1. Import package → create job → `POST /api/jobs/{id}/exports` (deprecated alias: `/wattlab/dumps`)
2. Download `openfdd_engineering_bundle_v1` zip
3. Optional offline: [`scripts/eplus_dump_clustering_export.py`](../../scripts/eplus_dump_clustering_export.py)

Validate structure:

```bash
python3 scripts/openfdd_bundle_validate.py validate path/to/bundle.zip
```

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

- Product export: `services/central/src/engineering_bundle.rs` (Rust; no Python in image)
- Offline parity: `tools/wattlab_export/` (`OPENFDD_WATTLAB_PYTHON_EXPORT=1`)
- Compare helpers (tests): `scripts/eplus_parity_compare.py`
- Retired vibe19 dual-parity: `scripts/retired/vibe19-parity/`
