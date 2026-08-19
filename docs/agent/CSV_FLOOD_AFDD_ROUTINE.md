---
title: CSV flood sim + AFDD routine
parent: External agents
nav_order: 20
---

# CSV flood simulation + updatable AFDD routine

Real BAS integrations **stream telemetry** (hourly CSV/API pulls), not one-shot package zips. OpenFDD models this with package seed + append + session-config + registry FDD run.

## APIs (product)

| Step | Method | Path |
|------|--------|------|
| Seed site | POST | `/api/csv/import/package` |
| Hourly append | POST | `/api/csv/import/package/append` (`confirm: true`, JWT) |
| Rule tuning | PUT | `/api/fdd/session-config` (`params` per rule) |
| Run AFDD | POST | `/api/fdd/run` (`mode: registry`, `building_id`, optional `rule_ids`, `params`) |

See also [CSV batch driver](../drivers/csv-batch.html) and [CSV batch import (web)](../web-app/csv-batch-import.html).

## Bench orchestrator

[`scripts/csv_flood_afdd_routine_sim.py`](../../scripts/csv_flood_afdd_routine_sim.py) drives **Liberty BUILDING_50** (`raw_BUILDING_50_openfdd.zip`):

```bash
# Dry-run (slice zip into hourly buckets; no stack)
python3 scripts/csv_flood_afdd_routine_sim.py \
  --package /home/ben/raw_BUILDING_50_openfdd.zip \
  --building-id BUILDING_50 --max-hours 4 --dry-run

# Live: hour-0 seed + hourly appends + FDD after each step
OPENFDD_ADMIN_PASSWORD=… python3 scripts/csv_flood_afdd_routine_sim.py \
  --package /home/ben/raw_BUILDING_50_openfdd.zip \
  --seed-mode truncate-hour0 --max-hours 48 \
  --afdd-routine scripts/fixtures/b50_afdd_routine.json --afdd-every 1
```

**AFDD routine** JSON ([`scripts/fixtures/b50_afdd_routine.json`](../../scripts/fixtures/b50_afdd_routine.json)):

- `rule_ids` — rules in this routine
- `params` — per-rule thresholds (`confirm_min`, etc.)
- `patches[]` — mid-stream updates at `append_step` (operator tuning)

Artifacts: `reports/eplus-dump/artifacts/csv_flood_sim/BUILDING_50/sim_log.jsonl`.

## MCP equivalent (manual today)

1. `openfdd_csv_package_append` after seed import
2. `openfdd_fdd_session_config` GET/PUT for `params`
3. `openfdd_fdd_run` with `mode: registry` and `building_id`

Future: `openfdd_afdd_routine_run` tool wrapping the same JSON contract (see plan Phase 3b follow-ups).

## Parity testing

- **Synthetic-59:** `scripts/synthetic_59_*.py` (OpenFDD-only; vibe19 dual-parity retired)
- **Real-site stream sim:** this script on BUILDING_50 — not dump-vs-vibe19
