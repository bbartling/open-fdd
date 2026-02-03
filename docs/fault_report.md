---
title: Fault Reports
nav_order: 4
---

# Fault Reports

`open_fdd.reports` provides fault analytics: duration, motor runtime, and sensor stats when faults occur. All code is in `open_fdd/reports/fault_report.py`.

## summarize_fault

Compute analytics for a single fault flag column.

```python
from open_fdd.reports import summarize_fault, print_summary

summary = summarize_fault(
    df,
    flag_col="fc1_flag",
    timestamp_col="timestamp",
    motor_col="supply_vfd_speed",
    sensor_cols={"duct_static": "duct_static", "mat": "mat"},
)
print_summary(summary, "FC1 Low Duct Static")
```

**Returns:** Dict with `total_days`, `total_hours`, `hours_<flag>_mode`, `percent_true`, `percent_false`, `hours_motor_runtime` (if `motor_col`), and `flag_true_<label>` for each `sensor_col`.

## Full fault_report.py logic

```python
def summarize_fault(
    df: pd.DataFrame,
    flag_col: str,
    timestamp_col: Optional[str] = None,
    sensor_cols: Optional[Dict[str, str]] = None,
    motor_col: Optional[str] = None,
) -> Dict[str, Any]:
    if timestamp_col and timestamp_col in df.columns:
        df = df.set_index(timestamp_col)
    if not isinstance(df.index, pd.DatetimeIndex):
        return {"error": "DataFrame must have DatetimeIndex"}

    delta = df.index.to_series().diff()
    total_td = delta.sum()

    summary = {
        "total_days": round(total_td / pd.Timedelta(days=1), 2),
        "total_hours": round(total_td / pd.Timedelta(hours=1)),
        f"hours_{flag_col.replace('_flag','')}_mode": round(
            (delta * df[flag_col]).sum() / pd.Timedelta(hours=1)
        ),
        "percent_true": round(df[flag_col].mean() * 100, 2),
        "percent_false": round((100 - df[flag_col].mean() * 100), 2),
    }

    if motor_col and motor_col in df.columns:
        motor_on = df[motor_col].gt(0.01).astype(int)
        summary["hours_motor_runtime"] = round(
            (delta * motor_on).sum() / pd.Timedelta(hours=1), 2
        )

    if sensor_cols:
        fault_mask = df[flag_col] == 1
        for label, col in sensor_cols.items():
            if col in df.columns:
                summary[f"flag_true_{label}"] = round(df.loc[fault_mask, col].mean(), 2)

    return summary
```

- **`hours_<flag>_mode`** — Hours when the fault was active.
- **`hours_motor_runtime`** — Hours the motor ran (e.g. supply fan VFD &gt; 1%).
- **`flag_true_<label>`** — Mean value of a sensor when the fault was true.

## summarize_all_faults

Run analytics for all fault flag columns.

```python
from open_fdd.reports import summarize_all_faults, print_summary

results = summarize_all_faults(
    df_result,
    flag_cols=["fc1_flag", "fc3_flag"],
    motor_col="supply_vfd_speed",
)
for flag, summary in results.items():
    print_summary(summary, flag)
```

## print_summary

Pretty-print a summary dict.

```python
from open_fdd.reports import print_summary

print_summary(summary, "FC1 Low Duct Static")
# --- FC1 Low Duct Static ---
#   total days: 0.09
#   total hours: 2
#   hours fc1 mode: 1
#   percent true: 30.0
#   percent false: 70.0
#   hours motor runtime: 2.25
```
