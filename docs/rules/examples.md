---
title: Examples
parent: DataFusion SQL Rules
nav_order: 2
---

# SQL rule examples

Illustrative patterns — adapt table/column names to your site model and historian schema.

## Stale data

Detect points with no recent samples:

```sql
SELECT point_id, max(ts) AS last_ts
FROM historian
GROUP BY point_id
HAVING max(ts) < now() - interval '30' minute
```

## SAT vs OAT delta (illustrative)

```sql
SELECT equipment_id, avg(sat) - avg(oat) AS delta
FROM joined_trends
WHERE ts > now() - interval '1' hour
GROUP BY equipment_id
HAVING avg(sat) - avg(oat) < 5
```

## Validation before activate

Use the workbench **Test** action or:

```http
POST /api/fdd-rules/{rule_id}/test-sql
```

## Live validation tab

**Validation runs** (`/live-fdd-validation`) exercises BACnet → historian → DataFusion → fault confirmation end-to-end on a bench or site.

Start with one equipment scope, confirm historian rows in **Plots**, then widen rule scope.
