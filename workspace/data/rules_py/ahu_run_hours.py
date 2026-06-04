"""Compute supply-fan and RTU system run hours from polled wide-frame samples."""

def _cfg_list(cfg, key, default):
    raw = cfg.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(default)


def _fan_on_series(df, cfg):
    speed_col = str(cfg.get("fan_speed_col") or "supply-fan-speed-command")
    binary_col = str(cfg.get("fan_binary_col") or "supply-fan-start-stop-command")
    threshold = float(cfg.get("fan_on_threshold") or 5.0)

    speed = pd.to_numeric(df[speed_col], errors="coerce") if speed_col in df.columns else None
    fan_on = pd.Series(False, index=df.index)
    if speed is not None:
        fan_on = fan_on | (speed > threshold)

    if binary_col in df.columns:
        raw = df[binary_col]
        binary_num = pd.to_numeric(raw, errors="coerce")
        text = raw.astype(str).str.strip().str.lower()
        binary_on = (binary_num > 0.5) | text.isin(["active", "on", "true", "yes", "1", "running"])
        fan_on = fan_on | binary_on.fillna(False)

    return fan_on.fillna(False)


def _system_on_series(df, cfg, fan_on):
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
    system_on = fan_on.copy()
    for col in compressor_cols:
        if col not in df.columns:
            continue
        raw = df[col]
        num = pd.to_numeric(raw, errors="coerce")
        text = raw.astype(str).str.strip().str.lower()
        active = (num > 0.5) | text.isin(["active", "on", "true", "yes", "1", "running"])
        system_on = system_on | active.fillna(False)
    return system_on.fillna(False)


def _dt_hours(df, ts_col, max_gap_hours):
    ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    dt_forward = (ts.shift(-1) - ts).dt.total_seconds() / 3600.0
    typical = float(dt_forward.dropna().median()) if dt_forward.notna().any() else (1.0 / 60.0)
    if typical <= 0:
        typical = 1.0 / 60.0
    dt = dt_forward.fillna(typical).clip(lower=0)
    if max_gap_hours is not None:
        dt = dt.clip(upper=float(max_gap_hours))
    return dt


def _sum_hours(mask, dt_hours):
    return float(dt_hours.loc[mask.fillna(False)].sum())


# Script entry — executed by Rule Lab / FDD batch runner (mode=script).
ts_col = "timestamp" if "timestamp" in df.columns else ("ts" if "ts" in df.columns else None)
if ts_col is None:
    out = {
        "df": df,
        "events": [{"type": "error", "text": "timestamp column required for run-hour calc"}],
        "metrics": {},
    }
else:
    work = df.sort_values(ts_col).copy()
    fan_on = _fan_on_series(work, cfg)
    system_on = _system_on_series(work, cfg, fan_on)
    dt_hours = _dt_hours(work, ts_col, cfg.get("max_gap_hours", 2.0))

    fan_hours = _sum_hours(fan_on, dt_hours)
    system_hours = _sum_hours(system_on, dt_hours)

    from datetime import datetime, timedelta, timezone

    tz_offset = float(cfg.get("tz_offset_hours") if cfg.get("tz_offset_hours") is not None else -6)
    local_tz = timezone(timedelta(hours=tz_offset))
    ts = pd.to_datetime(work[ts_col], utc=True, errors="coerce")
    local = ts.dt.tz_convert(local_tz)
    start = int(cfg.get("occupied_start_hour") or 8)
    end = int(cfg.get("occupied_end_hour") or 17)
    occupied = (local.dt.weekday < 5) & (local.dt.hour >= start) & (local.dt.hour < end)
    unoccupied = ~occupied

    afterhours_fan_hours = _sum_hours(fan_on & unoccupied, dt_hours)
    occupied_fan_hours = _sum_hours(fan_on & occupied, dt_hours)

    work["fan_on"] = fan_on.astype(int)
    work["system_on"] = system_on.astype(int)
    work["dt_hours"] = dt_hours
    work["fan_run_hours"] = fan_on.astype(float) * dt_hours
    work["system_run_hours"] = system_on.astype(float) * dt_hours

    metrics = {
        "site_id": str(cfg.get("site_id") or ""),
        "equipment_id": str(cfg.get("equipment_id") or "acme-vm-bbartling-rtu-01"),
        "sample_rows": int(len(work)),
        "fan_run_hours": round(fan_hours, 3),
        "system_run_hours": round(system_hours, 3),
        "occupied_fan_run_hours": round(occupied_fan_hours, 3),
        "afterhours_fan_run_hours": round(afterhours_fan_hours, 3),
        "lookback_first_ts": str(ts.min()) if ts.notna().any() else "",
        "lookback_last_ts": str(ts.max()) if ts.notna().any() else "",
    }
    print(
        "AHU run hours: fan={fan_run_hours:.2f}h system={system_run_hours:.2f}h "
        "after-hours fan={afterhours_fan_run_hours:.2f}h".format(**metrics)
    )
    out = {
        "df": work.tail(120),
        "events": [{"type": "metrics", "metrics": metrics}],
        "metrics": metrics,
    }
