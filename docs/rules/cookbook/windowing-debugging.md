---
title: Windowing & debugging
parent: Rule Cookbook
nav_order: 7
---

# Windowing & debugging

## Historian lookback vs rolling window

| | **Historian lookback** | **Rolling window (rule logic)** |
|---|------------------------|----------------------------------|
| Set by | SQL FDD test window, validation tab, API | Rule expression / Pandas `.rolling()` |
| Typical | 1–24 h for test | 12 samples ≈ 1 h @ 5 min poll |
| Edge SQL | Use `confirmation_seconds` for debounce | Full rolling: prefer Pandas off-edge |

## Debug workflow (edge)

1. **Plots** — confirm columns exist and values move
2. **SQL FDD** — run SELECT without `fault_raw` first to inspect rows
3. **Test SQL** — add `fault_raw`, set `confirmation_seconds`
4. **Validation tab** — overlay faults on live trends
5. **API health** — `GET /api/agent/validate` for feather/historian parity

## Null handling

Missing BACnet samples → NULL in pivot. Always:

```sql
WHEN oa_t IS NULL THEN false
```

Never let NULL propagate to `fault_raw = true`.

## Command scaling

Sites differ on 0–1 vs 0–100 % for valves and fans. Normalize in:

- Assignment transforms, or
- SQL: `CASE WHEN fan_cmd > 1 THEN fan_cmd/100.0 ELSE fan_cmd END`

## Compare SQL vs Pandas

1. Export same window from historian
2. Run Pandas mask ([cookbook](pandas-cookbook.html))
3. Run `test-sql` on edge
4. Diff flagged timestamps — should align within one poll period

## Common failures

| Symptom | Check |
|---------|--------|
| Zero rows | Wrong `equipment_id` or empty pivot |
| Always false | NULL inputs; wrong column name |
| Always true | Missing NULL guard; threshold too tight |
| No faults on dashboard | Rule not **activated**; confirmation too long |
