# BACnet direct vs Niagara bench validation

Local **benserver** read-only cross-check: same physical BACnet device via two paths.

## Topology

```text
BENS BENCHTEST BOX (BACnet device 5007, MS/TP 2000:7)
  ├─ Open-FDD native BACnet poll (commission agent → samples.csv → feather source=bacnet)
  └─ Niagara Windows station → baskStream WebSocket → Open-FDD Niagara driver (source=niagara_baskstream)
```

## Quick start

```bash
export OPENFDD_NIAGARA_ADMIN_PASSWORD='…'   # never commit
python3 scripts/bootstrap_bench_dual_source.py
python3 scripts/bench_validate_bacnet_vs_niagara.py --write-report
```

Or via API (bridge running):

```bash
curl -X POST http://127.0.0.1:8765/api/bench/validate/bacnet-vs-niagara \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"write_report": true}'
```

## Mapping config

Edit `workspace/data/bench_bacnet_vs_niagara.yaml` for semantic point mapping, tolerances, and Niagara ORDs (`$20` / `$2d` preserved).

## Brick model

Import dual-source semantics:

```bash
# Included in bootstrap; or manually:
python3 -c "
import json, os, sys
from pathlib import Path
REPO = Path('.').resolve()
sys.path.insert(0, str(REPO/'workspace/api'))
os.environ['OFDD_DESKTOP_DATA_DIR'] = str(REPO/'workspace/data')
from openfdd_bridge.model_service import ModelService
from openfdd_bridge.ttl_service import TtlService
ModelService().import_json(json.loads((REPO/'workspace/data/bench_dual_source_model.json').read_text()), replace=False)
TtlService().sync()
"
```

## Normalized data model

All drivers normalize through `driver_point_contract.py`:

- **bacnet** → canonical `bacnet_direct`
- **niagara_baskstream**, **modbus**, **json_api**

Semantic identity (`fdd_input` / `cross_source_semantic`) links both sources to one Brick point role.

## Poll intervals

- BACnet: `poll_interval_s` in `points.csv` (standard: 60, 300, …)
- Niagara: `poll_interval_seconds` on station config; worker re-reads each cycle (no restart required)
- Lab minimum Niagara interval: 15s (API validates ≥15)

Validate cadence: `GET /api/bench/poll-cadence?source=bacnet_direct&expected_interval_s=60`

## Overnight smoke

```bash
python3 scripts/run_overnight_bench_smoke.py --dry-run   # one checkpoint
python3 scripts/run_overnight_bench_smoke.py             # 12h, checkpoint every 2h
```

Reports: `reports/overnight_bench/<timestamp>/`

## Read-only rules

No BACnet writes, no Niagara overrides, no alarm ack. Relay booleans are read-only observations only.
