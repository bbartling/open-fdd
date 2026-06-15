"""Data-model-driven fault insight: per-sensor PyArrow stats (fault vs OK, motor-filtered)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .timeseries_api import historian_column_candidates, plot_column_name

MOTOR_BRICK_HINTS = ("Fan", "Pump", "Motor", "Compressor", "Blower")
RUN_STATUS_BRICK = frozenset(
    {
        "Fan_Status",
        "Fan_Status_Sensor",
        "Pump_Status",
        "Pump_Status_Sensor",
        "Motor_Status",
        "On_Off_Status",
        "Run_Status",
        "Supply_Fan_Speed_Sensor",
        "Return_Fan_Speed_Sensor",
        "Fan_Speed_Command",
    }
)


def _is_motor_point(pt: dict[str, Any]) -> bool:
    brick = str(pt.get("brick_type") or "").strip()
    if not brick:
        return False
    if brick in RUN_STATUS_BRICK:
        return True
    return any(h in brick for h in MOTOR_BRICK_HINTS)


def _motor_threshold(brick: str) -> float:
    if brick in RUN_STATUS_BRICK or "Status" in brick:
        return 0.5
    return 0.01


def _equipment_index(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        sid = str(eq.get("site_id") or "").strip()
        if sid and sid != site_id:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            out[eid] = eq
    return out


def _parent_equipment_ids(model: dict[str, Any], site_id: str, equipment_id: str) -> list[str]:
    eid = str(equipment_id or "").strip()
    if not eid:
        return []
    parents: list[str] = []
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        if str(eq.get("site_id") or "").strip() not in {"", site_id}:
            continue
        feeds = eq.get("feeds") if isinstance(eq.get("feeds"), list) else []
        if eid in {str(f).strip() for f in feeds}:
            pid = str(eq.get("id") or "").strip()
            if pid:
                parents.append(pid)
    return parents


def motor_points_for_equipment(
    model: dict[str, Any],
    site_id: str,
    equipment_id: str,
) -> list[dict[str, Any]]:
    eq_ids = {str(equipment_id or "").strip()} if equipment_id else set()
    for pid in _parent_equipment_ids(model, site_id, equipment_id):
        eq_ids.add(pid)
    eq_ids.discard("")

    motors: list[dict[str, Any]] = []
    eq_index = _equipment_index(model, site_id)
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        if str(pt.get("site_id") or "").strip() not in {"", site_id}:
            continue
        eid = str(pt.get("equipment_id") or "").strip()
        if eid not in eq_ids or not _is_motor_point(pt):
            continue
        col = plot_column_name(pt)
        if not col:
            continue
        eq = eq_index.get(eid) or {}
        brick = str(pt.get("brick_type") or "")
        motors.append(
            {
                "point_id": str(pt.get("id") or ""),
                "column": col,
                "label": str(pt.get("description") or pt.get("name") or col),
                "brick_type": brick,
                "equipment_id": eid,
                "equipment_name": str(eq.get("name") or eid),
                "threshold": _motor_threshold(brick),
            }
        )
    return motors


def _point_sensor_meta(pt: dict[str, Any], eq_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eid = str(pt.get("equipment_id") or "").strip()
    eq = eq_index.get(eid) or {}
    col = plot_column_name(pt)
    return {
        "point_id": str(pt.get("id") or ""),
        "column": col,
        "label": str(pt.get("description") or pt.get("name") or pt.get("fdd_input") or col),
        "brick_type": str(pt.get("brick_type") or ""),
        "fdd_input": str(pt.get("fdd_input") or ""),
        "equipment_id": eid,
        "equipment_name": str(eq.get("name") or eid),
    }


def resolve_sensor_columns(
    model: dict[str, Any],
    site_id: str,
    *,
    equipment_id: str = "",
    rule_id: str = "",
    analytics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """BRICK/model-driven sensor list for a fault (multi-sensor rules included)."""
    analytics = analytics or {}
    eq_index = _equipment_index(model, site_id)
    pt_index = {
        str(p.get("id") or ""): p
        for p in model.get("points") or []
        if isinstance(p, dict) and str(p.get("id") or "")
    }
    seen: set[str] = set()
    sensors: list[dict[str, Any]] = []

    def _add(pt: dict[str, Any]) -> None:
        meta = _point_sensor_meta(pt, eq_index)
        col = str(meta.get("column") or "").strip()
        if not col or col in seen:
            return
        seen.add(col)
        sensors.append(meta)

    for raw in analytics.get("value_columns") or analytics.get("flagged_columns") or []:
        col = str(raw or "").strip()
        if not col:
            continue
        for pt in model.get("points") or []:
            if not isinstance(pt, dict):
                continue
            if str(pt.get("site_id") or "").strip() not in {"", site_id}:
                continue
            if col in historian_column_candidates(pt) or plot_column_name(pt) == col:
                _add(pt)
                break
        else:
            if col not in seen:
                seen.add(col)
                sensors.append(
                    {
                        "point_id": "",
                        "column": col,
                        "label": col,
                        "brick_type": "",
                        "fdd_input": "",
                        "equipment_id": equipment_id,
                        "equipment_name": str((eq_index.get(equipment_id) or {}).get("name") or equipment_id),
                    }
                )

    if rule_id:
        from .fdd_equipment import bound_point_ids_for_rule

        for pid in bound_point_ids_for_rule(rule_id):
            pt = pt_index.get(pid)
            if isinstance(pt, dict):
                _add(pt)

        try:
            from .rule_store import RuleStore

            for rule in RuleStore().list_rules():
                if str(rule.get("id") or "") != rule_id:
                    continue
                bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
                brick_types = {str(b).strip() for b in bindings.get("brick_types") or [] if str(b).strip()}
                equip_ids = {str(e).strip() for e in bindings.get("equipment_ids") or [] if str(e).strip()}
                if equipment_id:
                    equip_ids.add(equipment_id)
                for pt in model.get("points") or []:
                    if not isinstance(pt, dict):
                        continue
                    if str(pt.get("site_id") or "").strip() not in {"", site_id}:
                        continue
                    if brick_types and str(pt.get("brick_type") or "") not in brick_types:
                        continue
                    if equip_ids and str(pt.get("equipment_id") or "") not in equip_ids:
                        continue
                    if brick_types or equip_ids:
                        _add(pt)
                break
        except Exception:
            pass

    if not sensors and equipment_id:
        for pt in model.get("points") or []:
            if not isinstance(pt, dict):
                continue
            if str(pt.get("equipment_id") or "") == equipment_id:
                _add(pt)

    return sensors


def _read_site_table(site_id: str, columns: list[str]):
    from .feather_store import FeatherStore

    store = FeatherStore()
    read_cols = ["timestamp", *dict.fromkeys(c for c in columns if c)]
    for source in ("bacnet", "niagara_baskstream", "modbus", "json_api"):
        table = store.read_site_table(site_id, source=source, columns=read_cols)
        if table is not None and table.num_rows > 0:
            return table, source
    return None, ""


def _trim_lookback(table, hours: float = 24.0):
    import pyarrow as pa
    import pyarrow.compute as pc

    if table is None or table.num_rows == 0 or "timestamp" not in table.column_names:
        return table
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1.0, hours))
    ts_col = table.column("timestamp")
    if pa.types.is_string(ts_col.type) or pa.types.is_large_string(ts_col.type):
        parsed = pc.cast(ts_col, pa.timestamp("us", tz="UTC"))
    else:
        parsed = ts_col
    mask = pc.greater_equal(parsed, pa.scalar(cutoff, type=parsed.type))
    filtered = table.filter(mask)
    return filtered if filtered.num_rows > 0 else table


def _float_column(table, column: str):
    import pyarrow as pa
    import pyarrow.compute as pc

    if table is None or column not in table.column_names:
        return None
    return pc.cast(table.column(column), pa.float64())


def _valid_numeric_mask(vals) -> Any:
    import pyarrow.compute as pc

    return pc.is_valid(vals)


def _column_stats_masked(vals, row_mask=None) -> dict[str, Any]:
    import pyarrow.compute as pc

    if vals is None:
        return {}
    if row_mask is not None:
        vals = pc.filter(vals, row_mask)
    valid = _valid_numeric_mask(vals)
    vals = pc.filter(vals, valid)
    if vals.length() == 0:
        return {}
    return {
        "count": int(vals.length()),
        "avg": round(float(pc.mean(vals).as_py()), 2),
        "min": round(float(pc.min(vals).as_py()), 2),
        "max": round(float(pc.max(vals).as_py()), 2),
    }


def _out_of_bounds_mask(vals, bounds_low: float | None, bounds_high: float | None):
    import pyarrow as pa
    import pyarrow.compute as pc

    if bounds_low is None and bounds_high is None:
        return None
    fault = None
    if bounds_low is not None:
        fault = pc.less(vals, pa.scalar(float(bounds_low)))
    if bounds_high is not None:
        high = pc.greater(vals, pa.scalar(float(bounds_high)))
        fault = high if fault is None else pc.or_(fault, high)
    return fault


def _motor_on_mask(table, motors: list[dict[str, Any]]):
    import pyarrow as pa
    import pyarrow.compute as pc

    if not motors or table is None:
        return None
    on = None
    for m in motors:
        mcol = str(m.get("column") or "")
        if not mcol or mcol not in table.column_names:
            continue
        threshold = float(m.get("threshold") or 0.5)
        mvals = pc.cast(table.column(mcol), pa.float64())
        this_on = pc.greater_equal(mvals, pa.scalar(threshold))
        on = this_on if on is None else pc.or_(on, this_on)
    return on


def _sensor_analytics_pyarrow(
    table,
    column: str,
    *,
    motors: list[dict[str, Any]],
    bounds_low: float | None,
    bounds_high: float | None,
) -> dict[str, Any]:
    import pyarrow.compute as pc

    vals = _float_column(table, column)
    if vals is None:
        return {}

    valid = _valid_numeric_mask(vals)
    overall = _column_stats_masked(vals, valid)
    if not overall:
        return {}

    out: dict[str, Any] = {
        "sample_count": overall.get("count"),
        "avg_overall": overall.get("avg"),
        "min_overall": overall.get("min"),
        "max_overall": overall.get("max"),
    }

    fault_mask = _out_of_bounds_mask(vals, bounds_low, bounds_high)
    if fault_mask is not None:
        fault_rows = pc.and_(valid, fault_mask)
        ok_rows = pc.and_(valid, pc.invert(fault_mask))
        fault_stats = _column_stats_masked(vals, fault_rows)
        ok_stats = _column_stats_masked(vals, ok_rows)
        if fault_stats:
            out["avg_while_fault"] = fault_stats.get("avg")
            out["min_while_fault"] = fault_stats.get("min")
            out["max_while_fault"] = fault_stats.get("max")
            out["fault_sample_count"] = fault_stats.get("count")
        if ok_stats:
            out["avg_while_ok"] = ok_stats.get("avg")
            out["min_while_ok"] = ok_stats.get("min")
            out["max_while_ok"] = ok_stats.get("max")
            out["ok_sample_count"] = ok_stats.get("count")
        fc = int(fault_stats.get("count") or 0)
        tc = int(overall.get("count") or 0)
        if tc:
            out["fault_sample_pct"] = round(100.0 * fc / tc, 1)

    motor_on = _motor_on_mask(table, motors)
    if motor_on is not None:
        motor_valid = pc.and_(valid, motor_on)
        run_stats = _column_stats_masked(vals, motor_valid)
        if run_stats:
            out["avg_while_motor_run"] = run_stats.get("avg")
            out["motor_run_sample_count"] = run_stats.get("count")
        if fault_mask is not None:
            motor_fault = pc.and_(motor_valid, fault_mask)
            mf_stats = _column_stats_masked(vals, motor_fault)
            if mf_stats:
                out["avg_while_motor_run_fault"] = mf_stats.get("avg")

    return out


def _motor_run_hours(table, motor_col: str, *, threshold: float) -> float:
    from .rcx.motor_runtime import _hours_on_from_table

    if table is None:
        return 0.0
    hours, _samples = _hours_on_from_table(table, motor_col, threshold=threshold)
    return float(hours)


def _pick_bounds(rule_config: dict[str, Any], analytics: dict[str, Any]) -> tuple[float | None, float | None]:
    lo = analytics.get("bounds_low")
    hi = analytics.get("bounds_high")
    if lo is None and rule_config.get("bounds_low") is not None:
        try:
            lo = float(rule_config["bounds_low"])
        except (TypeError, ValueError):
            pass
    if hi is None and rule_config.get("bounds_high") is not None:
        try:
            hi = float(rule_config["bounds_high"])
        except (TypeError, ValueError):
            pass
    if lo is None and rule_config.get("bounds_low_rh") is not None:
        try:
            lo = float(rule_config["bounds_low_rh"])
        except (TypeError, ValueError):
            pass
    if hi is None and rule_config.get("bounds_high_rh") is not None:
        try:
            hi = float(rule_config["bounds_high_rh"])
        except (TypeError, ValueError):
            pass
    return lo, hi


def enrich_fault_insight(
    *,
    model: dict[str, Any],
    site_id: str,
    equipment_id: str,
    sensor_column: str = "",
    rule_id: str = "",
    analytics: dict[str, Any] | None = None,
    rule_config: dict[str, Any] | None = None,
    lookback_hours: float = 24.0,
) -> dict[str, Any]:
    """Build operator-facing insight stats from model + PyArrow historian."""
    analytics = dict(analytics or {})
    cfg = rule_config or {}
    bounds_low, bounds_high = _pick_bounds(cfg, analytics)

    sensors = resolve_sensor_columns(
        model,
        site_id,
        equipment_id=equipment_id,
        rule_id=rule_id,
        analytics=analytics,
    )
    primary_col = str(sensor_column or "").strip()
    if not primary_col and sensors:
        primary_col = str(sensors[0].get("column") or "")
    if not sensors and primary_col:
        sensors = [{"column": primary_col, "label": primary_col, "point_id": "", "brick_type": "", "equipment_id": equipment_id, "equipment_name": ""}]

    insight: dict[str, Any] = {
        "sensor_column": primary_col,
        "lookback_hours": lookback_hours,
        "sensor_count": len(sensors),
    }

    for key in ("bounds_low", "bounds_high", "bounds_low_rh", "bounds_high_rh", "window_samples", "flatline_tolerance"):
        if cfg.get(key) is not None and str(cfg.get(key)).strip() != "":
            insight[f"rule_{key}"] = cfg.get(key)

    for key in ("bounds_low", "bounds_high", "avg_value_fault", "min_value_fault", "max_value_fault", "value_unit"):
        if analytics.get(key) is not None:
            insight[key] = analytics[key]

    if not site_id or not sensors:
        return insight

    motors = motor_points_for_equipment(model, site_id, equipment_id)
    motor_cols = [m["column"] for m in motors if m.get("column")]
    all_cols = list(dict.fromkeys([*(s["column"] for s in sensors if s.get("column")), *motor_cols]))
    table, source = _read_site_table(site_id, all_cols)
    if table is None:
        if analytics.get("avg_value_fault") is not None:
            insight["avg_while_fault"] = analytics["avg_value_fault"]
        return insight

    table = _trim_lookback(table, hours=lookback_hours)
    insight["historian_source"] = source

    sensor_rows: list[dict[str, Any]] = []
    for s in sensors:
        col = str(s.get("column") or "")
        if not col:
            continue
        row = dict(s)
        row.update(
            _sensor_analytics_pyarrow(
                table,
                col,
                motors=motors,
                bounds_low=bounds_low,
                bounds_high=bounds_high,
            )
        )
        sensor_rows.append(row)

    insight["sensors"] = sensor_rows

    primary = next((r for r in sensor_rows if r.get("column") == primary_col), sensor_rows[0] if sensor_rows else {})
    for key in (
        "avg_overall",
        "min_overall",
        "max_overall",
        "avg_while_fault",
        "avg_while_ok",
        "avg_while_motor_run",
        "avg_while_motor_run_fault",
        "fault_sample_pct",
        "sample_count",
        "fault_sample_count",
        "ok_sample_count",
        "motor_run_sample_count",
    ):
        if primary.get(key) is not None:
            insight[key] = primary[key]

    if analytics.get("avg_value_fault") is not None and insight.get("avg_while_fault") is None:
        insight["avg_while_fault"] = analytics["avg_value_fault"]

    if motors:
        primary_motor = motors[0]
        mcol = str(primary_motor.get("column") or "")
        if mcol in (table.column_names if table is not None else []):
            insight["motor_runtime_hours"] = _motor_run_hours(
                table, mcol, threshold=float(primary_motor.get("threshold") or 0.5)
            )
            insight["motor_label"] = primary_motor.get("label") or mcol
            insight["motor_equipment"] = primary_motor.get("equipment_name") or primary_motor.get("equipment_id")

    return insight


def merge_rule_config(rule_id: str) -> dict[str, Any]:
    if not rule_id:
        return {}
    try:
        from .rule_store import RuleStore

        for rule in RuleStore().list_rules():
            if not isinstance(rule, dict):
                continue
            if str(rule.get("id") or "") == rule_id:
                cfg = rule.get("config")
                return dict(cfg) if isinstance(cfg, dict) else {}
    except Exception:
        pass
    return {}
