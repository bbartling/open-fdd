---
title: Pandas cookbook
parent: Rule Cookbook
nav_order: 2
---

# Pandas cookbook (community / off-edge)

**Not used inside Open-FDD GHCR images.** This guide is for energy analysts, RCx engineers, and data scientists who work in **Jupyter**, **CSV exports**, or legacy workflows — with **parallel logic** to the [DataFusion SQL cookbook](datafusion-sql-cookbook.html).

## Setup

```python
import pandas as pd
import numpy as np

# Wide historian export (one row per timestamp × equipment)
df = pd.read_json("telemetry_pivot.jsonl", lines=True)
# Or: df = pd.read_feather("telemetry_pivot.feather")

df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values(["equipment_id", "timestamp"])
```

Use the **same column names** as your Open-FDD FDD inputs (`oa_t`, `sat`, `mat`, …).

---

## Helper: normalize command 0–100 → 0–1

```python
def norm_cmd(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    return np.where(s > 1.0, s / 100.0, s)
```

---

## 1. OA temperature out of range

```python
def fault_oa_temp_oob(row_df: pd.DataFrame) -> pd.Series:
    oa = row_df["oa_t"]
    return oa.notna() & ((oa < 40.0) | (oa > 110.0))

mask = fault_oa_temp_oob(df[df["equipment_id"] == "equip:validation"])
df.loc[mask.index, "fault_raw"] = mask
```

Vectorized (whole frame):

```python
df["fault_raw"] = df["oa_t"].notna() & (
    (df["oa_t"] < 40.0) | (df["oa_t"] > 110.0)
)
```

---

## 2. SAT deviation from setpoint

```python
df["fault_raw"] = (
    df["sat"].notna() & df["sat_sp"].notna()
    & (df["sat"].sub(df["sat_sp"]).abs() > 5.0)
)
```

---

## 3. Duct static low at full fan (GL36 Rule A)

```python
fan = norm_cmd(df["fan_cmd"])
df["fault_raw"] = (
    df["duct_static"].notna()
    & df["duct_static_sp"].notna()
    & (df["duct_static"] < df["duct_static_sp"] - 0.12)
    & (fan >= 0.87)
)
```

---

## 4. Mixed air envelope (GL36 Rules B & C)

```python
tol = 1.15
mat, oat, rat = df["mat"], df["oat"], df["rat"]
fan = norm_cmd(df["fan_cmd"])
running = fan > 0.01

below = running & mat.notna() & oat.notna() & rat.notna() & (
    (mat - tol) < np.minimum(rat - tol, oat - tol)
)
above = running & mat.notna() & oat.notna() & rat.notna() & (
    (mat - tol) > np.maximum(rat + tol, oat + tol)
)
df["fault_raw"] = below | above
```

---

## 5. Flatline (stuck sensor) — 12 samples ≈ 1 h @ 5 min

SQL on edge uses confirmation; Pandas can detect flatline directly:

```python
WINDOW = 12
TOL = 0.10

def flatline_mask(series: pd.Series) -> pd.Series:
    roll = series.rolling(WINDOW, min_periods=WINDOW)
    return (roll.max() - roll.min()).abs() <= TOL

df["fault_flatline"] = (
    df.groupby("equipment_id")["zone_t"]
    .transform(flatline_mask)
)
```

---

## 6. Rate of change spike

```python
MAX_DELTA_PER_HOUR = 12.0  # °F for OAT
SAMPLES_PER_HOUR = 12

df["oa_t_diff"] = df.groupby("equipment_id")["oa_t"].diff()
df["fault_roc"] = df["oa_t_diff"].abs() > (MAX_DELTA_PER_HOUR / SAMPLES_PER_HOUR)
```

---

## 7. Heating + cooling simultaneous

```python
df["fault_raw"] = (
    (df["htg_valve_pct"] > 10) & (df["clg_valve_pct"] > 10)
)
```

---

## 8. Low chilled-water delta-T

```python
df["chw_dt"] = df["chw_return_t"] - df["chw_supply_t"]
df["fault_raw"] = (
    df["chw_pump_cmd"].astype(bool)
    & df["chw_dt"].notna()
    & (df["chw_dt"] < 4.0)
)
```

---

## 9. Fault confirmation (Pandas)

Mirror Open-FDD `confirmation_seconds` with consecutive True samples:

```python
def confirm_fault(raw: pd.Series, min_rows: int = 5) -> pd.Series:
    """True only after `min_rows` consecutive True in raw."""
    groups = (raw != raw.shift()).cumsum()
    streak = raw.groupby(groups).cumcount() + 1
    return raw & (streak >= min_rows)

df["fault_confirmed"] = (
    df.groupby("equipment_id")["fault_raw"]
    .transform(lambda s: confirm_fault(s, min_rows=5))
)
```

At 60 s poll, `min_rows=5` ≈ 5 minutes — same as SQL API `confirmation_seconds: 300`.

---

## VAV cooling request levels

GL36-style zone cooling request (0–3) for RCx reports — **not** an edge SQL rule:

```python
HIGH_DIFF_F, MED_DIFF_F = 5.0, 3.0
LOOP_ON, LOOP_OFF = 95.0, 85.0

def cooling_request(row):
    d = row["zone_t"] - row["zone_t_sp"]
    if d >= HIGH_DIFF_F:
        return 3
    if d >= MED_DIFF_F:
        return 2
    if row.get("zone_cool_loop", 0) > LOOP_ON:
        return 1
    return 0

df["cooling_req"] = df.apply(cooling_request, axis=1)
```

---

## Oscillation / hunting (rolling std)

PID hunting or stuck dampers — use rolling std off-edge; approximate on edge with long confirmation:

```python
WINDOW = 12  # ~1 h at 5-min poll
df["sat_std"] = df.groupby("equipment_id")["sat"].transform(
    lambda s: s.rolling(WINDOW, min_periods=WINDOW).std()
)
df["fault_raw"] = df["fan_cmd"].astype(bool) & (df["sat_std"] > 2.0)
```

---

## Export results for Open-FDD parity

After validating in Pandas, port the **boolean expression** to DataFusion SQL for production on the edge:

| Pandas | DataFusion SQL |
|--------|----------------|
| `s.notna()` | `col IS NOT NULL` |
| `a & b` | `a AND b` |
| `a \| b` | `a OR b` |
| `~a` | `NOT a` |
| `s.abs()` | `ABS(col)` |
| `np.minimum(a,b)` | `LEAST(a,b)` |
| `np.maximum(a,b)` | `GREATEST(a,b)` |

Test SQL with `POST /api/fdd-rules/{id}/test-sql` before activate.

---

## PyArrow note

Legacy Open-FDD Python used **PyArrow compute** (`pc.greater`, `mixing_envelope_mask`, …). For new off-edge work, prefer **Pandas** or **Polars**; the edge runtime is **SQL-only**.

**Next:** [DataFusion SQL cookbook](datafusion-sql-cookbook.html) · [Sensor validation](sensor-validation.html)
