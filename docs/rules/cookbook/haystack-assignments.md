---
title: Haystack → SQL columns
parent: Rule Cookbook
nav_order: 8
---

# Haystack assignments → SQL columns

Open-FDD rules never reference raw BACnet object IDs in production SQL. The binding chain is:

```
Driver point → Haystack point → FDD input → telemetry_pivot column
```

## Configure assignments

1. Commission drivers (BACnet / Modbus / Haystack / JSON)
2. Build Haystack model (equipment + points)
3. **Assignments** — map each FDD input to a Haystack point ([guide]({{ site.baseurl }}/modeling/assignments.html))
4. Historian pivot uses **FDD input IDs** as column names (`oa_t`, `sat`, `zone_t`, …)

## Discover column names

- **SQL FDD tab** — schema picker / `GET /api/fdd-schema/fdd-inputs`
- **Plots** — select equipment and points
- **API:**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/fdd-schema/tables | jq .
```

## Example mapping (illustrative)

| Haystack tag | FDD input | Pivot column |
|--------------|-----------|--------------|
| `oa-temp` sensor on AHU | `oa_t` | `oa_t` |
| SAT sensor | `sat` | `sat` |
| SAT setpoint | `sat_sp` | `sat_sp` |
| Zone temp | `zone_t` | `zone_t` |

Your site uses its own Haystack IDs; **equipment_id** in SQL is the assigned equip ref (e.g. `equip:ahu-1`).

## Brick / external timeseries (legacy expression rules)

Older YAML expression rules used Brick class names (`Supply_Air_Temperature_Sensor`). Open-FDD 3.3 uses **Haystack + assignments** on the edge. For offline Pandas work, map Brick → column via your exported model CSV or SPARQL.

## Validation equipment

Bench and docs often use `equip:validation` — replace with your scoped equipment in production rules:

```sql
WHERE equipment_id = 'equip:your-scope'
```

**Next:** [DataFusion SQL cookbook](datafusion-sql-cookbook.html)
