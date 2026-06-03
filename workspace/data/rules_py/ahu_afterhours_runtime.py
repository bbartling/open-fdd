"""Flag RTU supply fan running outside office hours when zone temps are satisfied."""

_fault_streak = 0


def _cfg_list(cfg, key, default):
    raw = cfg.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(default)


def _local_dt(ts_ms, tz_offset_hours):
    from datetime import datetime, timedelta, timezone

    utc = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
    local = utc.astimezone(timezone(timedelta(hours=float(tz_offset_hours))))
    return local


def _is_unoccupied(local_dt, cfg):
    start = int(cfg.get("occupied_start_hour") or 8)
    end = int(cfg.get("occupied_end_hour") or 17)
    weekday = int(local_dt.weekday())
    if weekday >= 5:
        return True
    hour = int(local_dt.hour)
    return hour < start or hour >= end


def _num(row, *keys):
    for key in keys:
        if not key:
            continue
        raw = row.get(key)
        if raw is None:
            continue
        try:
            if isinstance(raw, str) and not raw.strip():
                continue
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _fan_on(row, cfg):
    speed_col = str(cfg.get("fan_speed_col") or "supply-fan-speed-command")
    binary_col = str(cfg.get("fan_binary_col") or "supply-fan-start-stop-command")
    speed_key = str(cfg.get("fan_speed_key") or "Supply_Fan_Speed_Command")
    binary_key = str(cfg.get("fan_binary_key") or "Supply_Fan_Start_Stop_Command")
    threshold = float(cfg.get("fan_on_threshold") or 5.0)

    speed = _num(row, speed_key, speed_col)
    if speed is not None and speed > threshold:
        return True

    binary = row.get(binary_key)
    if binary is None:
        binary = row.get(binary_col)
    if binary is None:
        return False
    if isinstance(binary, str):
        text = binary.strip().lower()
        if text in {"active", "on", "true", "yes", "1", "running"}:
            return True
        if text in {"inactive", "off", "false", "no", "0", "stopped"}:
            return False
    try:
        return float(binary) > 0.5
    except (TypeError, ValueError):
        return False


def _zone_avg(row, cfg):
    cols = _cfg_list(
        cfg,
        "zone_avg_cols",
        [
            "averagespacetemperature-first-floor-area-2",
            "averagespacetemperature-second-floor-area-3",
        ],
    )
    vals = []
    for col in cols:
        val = _num(row, col)
        if val is not None:
            vals.append(val)
    if vals:
        return sum(vals) / len(vals)
    return _num(row, "Zone_Air_Temperature_Sensor", "avg_zone_temp")


def _zones_satisfied(row, cfg):
    avg = _zone_avg(row, cfg)
    if avg is None:
        return False
    low = float(cfg.get("zone_satisfied_low") or 68.0)
    high = float(cfg.get("zone_satisfied_high") or 76.0)
    return low <= avg <= high


def evaluate(row, cfg, prev_row=None, rows=None):
    global _fault_streak

    ts_ms = row.get("ts_ms")
    if ts_ms is None:
        return False

    tz_offset = float(cfg.get("tz_offset_hours") if cfg.get("tz_offset_hours") is not None else -6)
    local = _local_dt(ts_ms, tz_offset)
    unoccupied = _is_unoccupied(local, cfg)
    fan_on = _fan_on(row, cfg)
    zones_ok = _zones_satisfied(row, cfg)

    if unoccupied and fan_on and zones_ok:
        _fault_streak += 1
    else:
        _fault_streak = 0

    min_samples = int(cfg.get("min_fault_samples") or 10)
    if _fault_streak >= min_samples and _fault_streak == min_samples:
        sym = temp_unit_symbol(cfg)
        avg = _zone_avg(row, cfg)
        print(
            f"{row.get('ts')}  after-hours fan with satisfied zones  "
            f"avg_zone={avg:.1f}{sym}  local={local.strftime('%a %H:%M')}  streak={_fault_streak}"
        )
    return _fault_streak >= min_samples
