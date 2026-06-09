"""Compute supply-fan and RTU system run hours from PyArrow historian table (script mode)."""

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import _cfg_list, _fan_on_mask, _unoccupied_mask


def _system_on_mask(table, cfg, fan_on):
    compressor_cols = _cfg_list(
        cfg,
        "compressor_cols",
        [
            "compressor-1-command",
            "compressor-2-command",
            "compressor-3-command",
            "compressor-4-command",
        ],
    )
    mask = fan_on
    for col in compressor_cols:
        if col not in table.column_names:
            continue
        num = pc.cast(table[col], pa.float64())
        mask = pc.or_(mask, pc.greater(num, 0.5))
    return mask


def _dt_hours(table, ts_col, max_gap_hours):
    from open_fdd.arrow_runtime.windows import arrow_shift

    ts = pc.cast(table[ts_col], pa.timestamp("us", tz="UTC"))
    prev = arrow_shift(ts, 1)
    delta = pc.subtract(ts, prev)
    secs = pc.divide(pc.cast(delta, pa.int64()), 1_000_000)
    hours = pc.divide(pc.cast(secs, pa.float64()), 3600.0)
    py_hours = hours.to_pylist()
    valid = [h for h in py_hours[1:] if h is not None and h > 0]
    typical = sorted(valid)[len(valid) // 2] if valid else (1.0 / 60.0)
    capped = float(max_gap_hours or 2.0)
    out = [typical]
    for h in py_hours[1:]:
        if h is None or h <= 0:
            out.append(typical)
        else:
            out.append(min(float(h), capped))
    return pa.array(out, type=pa.float64())


def _sum_hours(mask, dt_hours):
    pairs = zip(mask.to_pylist(), dt_hours.to_pylist(), strict=False)
    return round(sum(h for m, h in pairs if m and h is not None), 3)


ts_col = "timestamp" if "timestamp" in table.column_names else ("ts" if "ts" in table.column_names else None)
if ts_col is None:
    out = {
        "events": [{"type": "error", "text": "timestamp column required for run-hour calc"}],
        "metrics": {},
    }
else:
    fan_on = _fan_on_mask(table, cfg)
    system_on = _system_on_mask(table, cfg, fan_on)
    dt = _dt_hours(table, ts_col, cfg.get("max_gap_hours", 2.0))
    unoccupied = _unoccupied_mask(table, cfg)
    occupied = pc.invert(unoccupied)

    fan_hours = _sum_hours(fan_on, dt)
    system_hours = _sum_hours(system_on, dt)
    afterhours_fan_hours = _sum_hours(pc.and_(fan_on, unoccupied), dt)
    occupied_fan_hours = _sum_hours(pc.and_(fan_on, occupied), dt)

    ts_list = table[ts_col].to_pylist()
    metrics = {
        "site_id": str(cfg.get("site_id") or ""),
        "equipment_id": str(cfg.get("equipment_id") or "acme-vm-bbartling-rtu-01"),
        "sample_rows": int(table.num_rows),
        "fan_run_hours": fan_hours,
        "system_run_hours": system_hours,
        "occupied_fan_run_hours": occupied_fan_hours,
        "afterhours_fan_run_hours": afterhours_fan_hours,
        "lookback_first_ts": str(ts_list[0]) if ts_list else "",
        "lookback_last_ts": str(ts_list[-1]) if ts_list else "",
    }
    print(
        "AHU run hours: fan={fan_run_hours:.2f}h system={system_run_hours:.2f}h "
        "after-hours fan={afterhours_fan_run_hours:.2f}h".format(**metrics)
    )
    out = {"events": [{"type": "metrics", "metrics": metrics}], "metrics": metrics}
