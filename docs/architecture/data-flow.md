---
title: Data flow
parent: Architecture
nav_order: 2
---

# Data flow

```text
Field buses (BACnet / Modbus / Haystack / JSON / CSV)
  → driver tree + discovery
  → Haystack model points + assignment graph
  → Arrow RecordBatches → Feather files on disk
  → DataFusion SQL rules
  → fault state, plots, PDF reports
  → React dashboard
```

## Driver → model → FDD

1. **Drivers** expose points in the driver tree (BACnet objects, Modbus registers, Haystack refs, JSON endpoints).
2. **Assignments** bind driver points to Haystack semantic IDs (`/api/model/assignments`).
3. **Historian** persists normalized samples under `workspace/data/historian/`.
4. **SQL rules** reference semantic point names via DataFusion — not raw BACnet instance numbers.
5. **Faults** surface on the dashboard and in exports/reports.

## CSV path

Engineering workstations can skip live drivers:

1. Import CSV via **CSV Fusion** tab or `/api/csv/import/*`
2. Preflight validation (`/api/csv/import/preflight`) gates execute
3. Historian rows carry `source_driver: csv` for downstream SQL

## Reports

Report builder pulls from model, historian, rules, and fault state → PDF via `/api/reports/*/render/pdf`.
