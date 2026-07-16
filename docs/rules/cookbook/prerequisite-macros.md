---
title: Prerequisite macros
parent: Rule Cookbook
nav_order: 8
---

# Reusable prerequisite macros

Composable guards used across rules. Compile to SQL `CASE` predicates or Pandas boolean masks. Reduces false positives from startup, unoccupied, override, and bad-sensor states.

---

## macro.occupancy_cooling

**Intent:** Rule applies only when zone/building is occupied and needs cooling (or neutral).

### DataFusion SQL

```sql
-- occ_mode: 'occupied' | 'unoccupied' | 'bypass' (site-specific enum)
(occ_mode = 'occupied' OR occ_mode IS NULL)
```

### Pandas

```python
def macro_occupancy_cooling(d: pd.DataFrame) -> pd.Series:
    occ = d.get("occ_mode")
    if occ is None:
        return pd.Series(True, index=d.index)
    return occ.eq("occupied") | occ.isna()
```

---

## macro.fan_proven_on

**Intent:** Supply fan commanded and proven (status feedback or inferred from static/flow).

### DataFusion SQL

```sql
(
  CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END >= 0.05
)
AND (
  fan_status IS NULL
  OR fan_status = true
  OR CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END >= 0.05
)
```

### Pandas

```python
def macro_fan_proven_on(d: pd.DataFrame) -> pd.Series:
    cmd = norm_cmd(d["fan_cmd"]) if "fan_cmd" in d else 0
    stat = d["fan_status"] if "fan_status" in d else True
    on = pd.Series(cmd, index=d.index) >= 0.05
    if isinstance(stat, pd.Series):
        return on & (stat.isna() | stat.astype(bool))
    return on
```

---

## macro.mode_delay

**Intent:** Suppress faults for N minutes after mode change (GL36-style startup delay).

### DataFusion SQL

```sql
-- Requires mode_change_ts column or infer from occ_mode / fan_cmd edges
-- Default: 300 s after fan transitions off→on
NOT (
  fan_cmd_rising
  AND timestamp < mode_change_ts + INTERVAL '300' SECOND
)
```

### Pandas

```python
MODE_DELAY_SECONDS = 300  # site-adjustable

def macro_mode_delay(d: pd.DataFrame, col: str = "fan_cmd") -> pd.Series:
    cmd = norm_cmd(d[col]) if col in d else pd.Series(0, index=d.index)
    rising = (cmd >= 0.05) & (cmd.shift(1).fillna(0) < 0.05)
    t0 = d["timestamp"].where(rising).ffill()
    elapsed = (d["timestamp"] - t0).dt.total_seconds()
    return elapsed.isna() | (elapsed >= MODE_DELAY_SECONDS)
```

---

## macro.steady_state_window

**Intent:** Require signal stability before evaluating control faults (e.g. hunting).

### DataFusion SQL

```sql
-- Use rolling stddev over last N samples; DataFusion window:
-- stddev(sat) OVER (ORDER BY timestamp ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) < 0.5
true  -- implement per-rule with window frame
```

### Pandas

```python
def macro_steady_state(series: pd.Series, window: int = 12, max_std: float = 0.5) -> pd.Series:
    return series.rolling(window, min_periods=window).std() <= max_std
```

---

## macro.reset_enabled

**Intent:** Reset logic is active (not fixed setpoint mode).

### DataFusion SQL

```sql
(reset_enable IS NULL OR reset_enable = true)
AND (override_active IS NULL OR override_active = false)
```

### Pandas

```python
def macro_reset_enabled(d: pd.DataFrame) -> pd.Series:
    en = d.get("reset_enable", True)
    ovr = d.get("override_active", False)
    if isinstance(en, pd.Series):
        base = en.isna() | en.astype(bool)
    else:
        base = pd.Series(True, index=d.index)
    if isinstance(ovr, pd.Series):
        return base & ~(ovr.fillna(False).astype(bool))
    return base
```

---

## macro.override_suppression

**Intent:** Skip fault when manual override, hand, or bypass active.

### DataFusion SQL

```sql
NOT (
  COALESCE(override_active, false) = true
  OR COALESCE(hand_mode, false) = true
  OR COALESCE(bypass_active, false) = true
)
```

### Pandas

```python
def macro_override_suppression(d: pd.DataFrame) -> pd.Series:
    flags = ["override_active", "hand_mode", "bypass_active"]
    mask = pd.Series(True, index=d.index)
    for f in flags:
        if f in d.columns:
            mask &= ~d[f].fillna(False).astype(bool)
    return mask
```

---

## macro.sensor_quality_gate

**Intent:** Exclude samples where prerequisite sensors fail quality checks.

### DataFusion SQL

```sql
oa_t IS NOT NULL AND oa_t >= 40.0 AND oa_t <= 110.0
AND (oa_t_stale IS NULL OR oa_t_stale = false)
```

### Pandas

```python
def macro_sensor_quality_gate(d: pd.DataFrame, col: str, lo: float, hi: float) -> pd.Series:
    s = d[col]
    ok = s.notna() & (s >= lo) & (s <= hi)
    stale_col = f"{col}_stale"
    if stale_col in d.columns:
        ok &= ~d[stale_col].fillna(False).astype(bool)
    return ok
```

---

## Composing macros in a rule

### SQL pattern

```sql
SELECT timestamp, equipment_id,
  CASE
    WHEN NOT (<macro.fan_proven_on>) THEN false
    WHEN NOT (<macro.override_suppression>) THEN false
    WHEN NOT (<macro.sensor_quality_gate on oa_t>) THEN false
    WHEN <detect condition> THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### Pandas pattern

```python
base = macro_fan_proven_on(d) & macro_override_suppression(d) & macro_sensor_quality_gate(d, "oa_t", 40, 110)
mask = base & detect_condition
d = apply_fault(d, mask)
```


---

## Validated catalog gates (vibe19)

The Streamlit-tested catalog wraps many rules with **operational gates** (fan proven-on, occupancy, override suppression, pressure-on proxies). Gates live alongside rule computes in the vibe19 `operational_gate` module — SQL recipes should replicate the same predicates before latching `fault_raw`.

See [Pandas cookbook](pandas-cookbook.html#setup--shared-helpers) and [parity matrix](parity-matrix.html).
