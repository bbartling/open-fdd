---
name: feather-local-storage
description: "Implements local pyarrow feather shard storage for site timeseries under a configurable data directory. Use when the manifest includes feather_storage or when ingest drivers persist metrics locally."
---

# Feather local storage

## When to use / When not to use

Use for on-disk timeseries shards per site and source (csv, weather, bacnet).

Skip when the operator keeps data in external DB or flat CSV only.

## Prerequisites

- `pyarrow` in the generated API environment.
- Data root via `OFDD_DESKTOP_DATA_DIR` or platform default under user data dir.

## Quick start

Layout under `<data_dir>/feather_store/<source>/<site_id>/` with timestamp-indexed shards.

```python
from pathlib import Path
import os
os.environ["OFDD_DESKTOP_DATA_DIR"] = "workspace/data"
# Implement FeatherStore read/write in workspace using legacy semantics (see reference).
```

## Core concepts

- `model.json` and `data_model.ttl` live beside feather root when BRICK model is enabled.
- Saved Python rules: `rules_store.json` + `rules_py/*.py` (see [rules-crud-and-batch-run](../rules-crud-and-batch-run/SKILL.md)).
- Purge vs delete site: expose via bridge storage endpoints.

## Compose with other skills

- [driver-csv-ingest](../driver-csv-ingest/SKILL.md), [brick-ttl-data-model](../brick-ttl-data-model/SKILL.md), [timeseries-plots-and-cleaning](../timeseries-plots-and-cleaning/SKILL.md)

## Verification

- Write a shard, list stats endpoint, read back with pandas.

## Gotchas

- Relative `OFDD_DESKTOP_DATA_DIR` resolves against process cwd.
- Windows uses `%APPDATA%/open-fdd-desktop` when env unset.

See [references/REFERENCE.md](references/REFERENCE.md).
