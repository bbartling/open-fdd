---
title: Fault confirmation
parent: Rule Cookbook
nav_order: 3
---

# Fault confirmation

A raw rule can flicker **true** for one poll cycle. Open-FDD applies **confirmation** after SQL evaluates `fault_raw`.

## Edge (DataFusion SQL)

Set on test or activate:

```json
{"confirmation_seconds": 300}
```

Or via API:

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT ... fault_raw FROM telemetry_pivot","confirmation_seconds":300}'
```

| Poll interval | `confirmation_seconds` | Approx. consecutive samples |
|---------------|------------------------|----------------------------|
| 60 s | 300 | ~5 |
| 60 s | 600 | ~10 |
| 300 s | 900 | ~3 |

## Rule design

1. SQL returns **`fault_raw`** per row (boolean).
2. Confirmation engine latches **`fault`** only after the condition holds for the configured duration.
3. Dashboard and `GET /api/faults` show **confirmed** faults.

## Pandas (off-edge)

See [Pandas cookbook — confirmation](pandas-cookbook.html#9-fault-confirmation-pandas).

## Bench defaults

Paired validation often uses **5-minute** confirmation to suppress toggles during BACnet/Haystack commissioning. Tune per site severity (comfort vs energy vs safety).
