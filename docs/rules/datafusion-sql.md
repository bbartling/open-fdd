---
title: DataFusion SQL
parent: DataFusion SQL Rules
nav_order: 1
---

# DataFusion SQL

## Rule lifecycle

1. Author SQL in the workbench or via API
2. Validate / test against historian sample
3. Activate rule
4. FDD run evaluates conditions → fault records

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rules` | Active rules |
| POST | `/api/rules/save` | Save rule |
| POST | `/api/rules/batch` | Batch update |
| PATCH | `/api/rules/{rule_id}` | Patch rule |
| POST | `/api/fdd/run` | Run FDD engine |
| POST | `/api/fdd-rules/{id}/validate-sql` | Syntax check |
| POST | `/api/fdd-rules/{id}/activate` | Activate |

## Schema helpers

| Method | Path |
|--------|------|
| GET | `/api/fdd-schema/tables` |
| GET | `/api/fdd-schema/fdd-inputs` |
| GET | `/api/fdd-schema/equipment-types` |

## Fault output

Faults appear on the dashboard and via:

- `GET /api/faults`
- `GET /api/dashboard/faults/active`
- `GET /api/faults/export.csv`

## Prerequisites

Configure [assignments]({{ site.baseurl }}/modeling/assignments.html) and confirm historian data in **Plots** before expecting faults.
