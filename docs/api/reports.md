---
title: Reports API
parent: API Reference
nav_order: 3
---

# Reports API

Programmatic Python API for fault analytics, visualization, and report generation. Used by analyst workflows, notebooks, and the standalone FDD runner to produce fault summaries, charts, and Word reports. Import from `open_fdd.reports`.

**Dependencies:** Core reporting uses pandas only. Word (.docx) reports require `python-docx` (`pip install python-docx`); without it, `build_report`, `events_from_dataframe`, and `events_to_summary_table` are unavailable.

---

## Fault report (fault_report)

Fault duration, time ranges, flatline periods, bounds/flatline episode analysis, and multi-equipment report building.

### time_range

Return a human-readable time range string for faulted rows.

```python
from open_fdd.reports import time_range

s = time_range(df, flag_col="flatline_flag", timestamp_col="timestamp")
# Returns "2025-01-01 03:00:00 to 2025-01-01 06:15:00" or "-" if no faults
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | DataFrame | Has fault flag column and timestamps. |
| `flag_col` | str | Name of fault flag column (0/1). |
| `timestamp_col` | str | Timestamp column (default: `"timestamp"`). |

---

### flatline_period_range

Return `(start_ts, end_ts)` for the full flatline period (including the window before the first flagged row). Use with `summarize_fault` so fault-period stats match.

```python
from open_fdd.reports import flatline_period_range

period = flatline_period_range(df, flag_col="flatline_flag", timestamp_col="timestamp", window=12)
# Returns (start_ts, end_ts) or None if no faults
```

---

### flatline_period

Same as `time_range` but for flatline rules: accounts for the rule’s `window` so the returned string covers the actual flat period, not just when the flag is 1.

```python
from open_fdd.reports import flatline_period

s = flatline_period(df, flag_col="flatline_flag", timestamp_col="timestamp", window=12)
```

---

### summarize_fault

Compute fault analytics for a single flag column: total days/hours, hours in fault mode, percent true/false, optional motor runtime, optional sensor stats during fault.

```python
from open_fdd.reports import summarize_fault

summary = summarize_fault(
    df,
    flag_col="flatline_flag",
    timestamp_col="timestamp",
    sensor_cols={"SAT": "SAT (°F)", "OAT": "OAT (°F)"},
    motor_col="Supply_Fan_Speed_Command",
    period_range=(start_ts, end_ts),  # optional, from flatline_period_range
)
# Returns dict: total_days, total_hours, hours_*_mode, percent_true, percent_hours_true,
# hours_motor_runtime (if motor_col), flag_true_* (if sensor_cols), fault_period_*
```

---

### summarize_all_faults

Run `summarize_fault` for each flag column and return a dict of summaries. Use with `build_report` (docx) or custom reporting.

```python
from open_fdd.reports import summarize_all_faults

summaries = summarize_all_faults(df, flag_cols, column_map, ...)
# Returns {flag_col: summary_dict, ...}
```

---

### analyze_bounds_episodes / analyze_flatline_episodes

Analyze contiguous episodes of bounds or flatline faults. Return episode lists with start/end and optional stats.

```python
from open_fdd.reports import analyze_bounds_episodes, analyze_flatline_episodes
```

---

### build_report_multi_equipment

Build a combined report across multiple equipment (e.g. multiple AHUs). Uses rules, column map, and result DataFrames.

```python
from open_fdd.reports import build_report_multi_equipment
```

---

### load_rules_for_report / sensor_cols_from_column_map / print_*

Helpers for report workflows: load rules, derive sensor columns from column_map, print column mapping or episode summaries.

---

## Fault visualization (fault_viz)

Event detection and plotting for notebooks and report charts.

### get_fault_events

Return list of `(start_iloc, end_iloc, flag_name)` for contiguous fault regions in a single flag column.

```python
from open_fdd.reports import get_fault_events

events = get_fault_events(df, flag_col="flatline_flag")
# Returns [(0, 42, "flatline_flag"), (100, 105, "flatline_flag"), ...]
```

---

### all_fault_events

Collect events from multiple flag columns, sorted by start index.

```python
from open_fdd.reports import all_fault_events

events = all_fault_events(df, flag_cols=["flatline_flag", "bad_sensor_flag"])
```

---

### build_rule_sensor_mapping / build_sensor_map_for_summarize

Build fault-to-sensor mappings from rules and column_map for use with `summarize_fault` and plots.

```python
from open_fdd.reports import build_rule_sensor_mapping, build_sensor_map_for_summarize
```

---

### plot_fault_analytics / plot_flag_true_bars / zoom_on_event

Plot fault analytics (e.g. flag-over-time, sensor values during faults). `zoom_on_event` produces a zoomed plot around a fault event; save the figure path for embedding in Word reports.

```python
from open_fdd.reports import plot_fault_analytics, plot_flag_true_bars, zoom_on_event
```

---

### run_fault_analytics

High-level: run analytics and optionally generate plots for all flags. Wraps the above for notebook-friendly use.

```python
from open_fdd.reports import run_fault_analytics
```

---

## Word reports (docx_generator)

Requires `python-docx`. Generate Word (.docx) reports with methodology, executive summary, charts, fault summary table, and recommendations.

### events_from_dataframe

Convert `(start_iloc, end_iloc, flag_name)` events to a list of dicts with `flag`, `start`, `end`, `duration_samples`. Use with `all_fault_events` output.

```python
from open_fdd.reports import events_from_dataframe

event_dicts = events_from_dataframe(df, events, timestamp_col="timestamp")
```

---

### events_to_summary_table

Convert event dicts to a DataFrame suitable for a table (Flag, Start, End, Duration).

```python
from open_fdd.reports import events_to_summary_table

table_df = events_to_summary_table(event_dicts)
```

---

### build_report

Build a full Word report: heading, methodology, executive summary, embedded charts, fault summary table, recommendations, optional rules reference.

```python
from open_fdd.reports import build_report

report_path = build_report(
    result=result_df,
    events=event_dicts,
    summaries=summaries,  # from summarize_all_faults
    output_dir=Path("reports"),
    equipment_name="AHU7",
    plot_paths=["reports/zoom_flatline_1.png"],
    methodology="Optional custom methodology text.",
    executive_summary="Optional pre-written summary.",
    recommendations=["Check sensor calibration.", "Review setpoints."],
    rules_reference="Optional YAML or text of rules used.",
)
# Returns Path to saved .docx (e.g. reports/FDD_Report_AHU7_2025-01-15.docx)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `result` | DataFrame | RuleRunner output with fault flag columns. |
| `events` | list[dict] | From `events_from_dataframe(all_fault_events(...))`. |
| `summaries` | dict | From `summarize_all_faults`. |
| `output_dir` | Path | Directory for report and any plots. |
| `equipment_name` | str | e.g. "AHU7", "Chiller Plant". |
| `plot_paths` | list[str], optional | Paths to plot images to embed. |
| `methodology`, `executive_summary`, `recommendations`, `rules_reference` | optional | Override default text. |

---

## Usage in analyst workflow

Typical flow:

1. Run RuleRunner on site/equipment data → `result` DataFrame.
2. `all_fault_events(result, flag_cols)` → events.
3. `events_from_dataframe(result, events)` → event dicts.
4. `summarize_all_faults(result, flag_cols, column_map, ...)` → summaries.
5. Optionally `zoom_on_event` or other plots → save paths.
6. `build_report(result, event_dicts, summaries, output_dir, equipment_name, plot_paths=...)` → .docx.

See `open_fdd.analyst.run_fdd` and analyst config (`reports_root`, `report_docx`) for how the platform uses these APIs.
