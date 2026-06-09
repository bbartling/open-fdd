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
    from datetime import datetime, timezone

    def _to_utc(val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=timezone.utc)

    ts_list = [_to_utc(v) for v in table[ts_col].to_pylist()]
    capped = float(max_gap_hours or 2.0)
    gaps: list[float] = []
    for i in range(1, len(ts_list)):
        cur, prev = ts_list[i], ts_list[i - 1]
        if cur is None or prev is None:
            continue
        gap_h = max(0.0, (cur - prev).total_seconds() / 3600.0)
        if gap_h > 0:
            gaps.append(min(gap_h, capped))
    typical = sorted(gaps)[len(gaps) // 2] if gaps else (1.0 / 60.0)
    out = [typical]
    for i in range(1, len(ts_list)):
        cur, prev = ts_list[i], ts_list[i - 1]
        if cur is None or prev is None:
            out.append(typical)
            continue
        gap_h = max(0.0, (cur - prev).total_seconds() / 3600.0)
        if gap_h <= 0:
            out.append(typical)
        else:
            out.append(min(gap_h, capped))
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
