---
name: driver-bacnet-ingest
description: "Builds BACnet polling ingest and commissioning UI for site timeseries. Use when drivers include bacnet or operators integrate field controllers."
---

# BACnet ingest driver

## Prerequisites

- **`bacnet_toolshed/`** in repo root (`pip install -r bacnet_toolshed/requirements.txt`)
- Bridge `GET/POST /config/bacnet`, `POST /ingest/bacnet`, driver health export (generate under `workspace/`)
- Commissioning CSV under `workspace/bacnet/commissioning/`

## Quick start (edge CLI)

```bash
export OPENFDD_REPO_ROOT=$PWD
python -m bacnet_toolshed.discover 0 4194303 \
  --name OpenFDD --instance 599999 --address <OT-NIC>/24:47808
python -m bacnet_toolshed.enable_points \
  --input workspace/bacnet/commissioning/points_discovered.csv \
  --output workspace/bacnet/commissioning/points.csv --all
python -m bacnet_toolshed.poll_driver \
  --config workspace/bacnet/commissioning/points.csv --interval 60 --once \
  --name OpenFDD --instance 599999 --address <OT-NIC>/24:47808
```

Poll output: `workspace/bacnet/polls/samples.csv` (long format). Ingest into Feather via bridge when implemented.

## Dashboard

React route **`/bacnet-tools`**: NIC args form, discover job status, points CSV editor (`enabled`, `brick_class`), link to poll health.

## Reference

- `bacnet_toolshed/README.md`
- `skills/fastapi-bridge-api`, `skills/feather-local-storage`, `skills/react-operator-dashboard`
