"""Data-model-driven fault insight: sensor stats, thresholds, motor run-hours."""

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
    """Equipment IDs that feed the given equipment (AHU → VAV)."""
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
    """Motor/fan status points on equipment and upstream feeders."""
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


def _column_stats(table, column: str, *, row_mask=None) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.compute as pc

    if table is None or column not in table.column_names:
        return {}
    col = table.column(column)
    if row_mask is not None:
        col = pc.filter(col, row_mask)
    if col.length() == 0:
        return {}
    try:
        cast = pc.cast(col, pa.float64())
    except Exception:
        return {}
    valid = pc.is_valid(cast)
    vals = pc.filter(cast, valid)
    if vals.length() == 0:
        return {}
    return {
        "count": int(vals.length()),
        "avg": round(float(pc.mean(vals).as_py()), 2),
        "min": round(float(pc.min(vals).as_py()), 2),
        "max": round(float(pc.max(vals).as_py()), 2),
    }


def _motor_run_hours(table, motor_col: str, *, threshold: float) -> float:
    from .rcx.motor_runtime import _hours_on_from_table

    if table is None:
        return 0.0
    hours, _samples = _hours_on_from_table(table, motor_col, threshold=threshold)
    return float(hours)


def enrich_fault_insight(
    *,
    model: dict[str, Any],
    site_id: str,
    equipment_id: str,
    sensor_column: str,
    analytics: dict[str, Any] | None = None,
    rule_config: dict[str, Any] | None = None,
    lookback_hours: float = 24.0,
) -> dict[str, Any]:
    """Build operator-facing insight stats from model + historian."""
    analytics = dict(analytics or {})
    cfg = rule_config or {}
    col = str(sensor_column or "").strip()
    if not col:
        cols = analytics.get("value_columns") or analytics.get("flagged_columns") or []
        col = str(cols[0] or "").strip() if cols else ""

    insight: dict[str, Any] = {
        "sensor_column": col,
        "lookback_hours": lookback_hours,
    }

    for key in ("bounds_low", "bounds_high", "bounds_low_rh", "bounds_high_rh", "window_samples", "flatline_tolerance"):
        if cfg.get(key) is not None and str(cfg.get(key)).strip() != "":
            insight[f"rule_{key}"] = cfg.get(key)

    for key in ("bounds_low", "bounds_high", "avg_value_fault", "min_value_fault", "max_value_fault", "value_unit"):
        if analytics.get(key) is not None:
            insight[key] = analytics[key]

    if analytics.get("fault_samples") is not None and analytics.get("total_samples"):
        total = int(analytics["total_samples"])
        fs = int(analytics["fault_samples"])
        insight["fault_sample_pct"] = round(100.0 * fs / max(total, 1), 1)

    if not site_id or not col:
        return insight

    motors = motor_points_for_equipment(model, site_id, equipment_id)
    motor_cols = [m["column"] for m in motors if m.get("column")]
    table, source = _read_site_table(site_id, [col, *motor_cols])
    if table is not None:
        table = _trim_lookback(table, hours=lookback_hours)
        insight["historian_source"] = source
        overall = _column_stats(table, col)
        if overall:
            insight["avg_overall"] = overall.get("avg")
            insight["min_overall"] = overall.get("min")
            insight["max_overall"] = overall.get("max")
            insight["sample_count_overall"] = overall.get("count")

        if motors:
            import pyarrow as pa
            import pyarrow.compute as pc

            primary = motors[0]
            mcol = str(primary["column"])
            threshold = float(primary.get("threshold") or 0.5)
            if mcol in table.column_names:
                mvals = pc.cast(table.column(mcol), pa.float64())
                on_mask = pc.greater_equal(mvals, pa.scalar(threshold))
                run_stats = _column_stats(table, col, row_mask=on_mask)
                if run_stats.get("count"):
                    insight["avg_while_motor_run"] = run_stats.get("avg")
                    insight["motor_run_sample_count"] = run_stats.get("count")
                insight["motor_runtime_hours"] = _motor_run_hours(table, mcol, threshold=threshold)
                insight["motor_label"] = primary.get("label") or mcol
                insight["motor_equipment"] = primary.get("equipment_name") or primary.get("equipment_id")

    if analytics.get("avg_value_fault") is not None:
        insight["avg_while_fault"] = analytics["avg_value_fault"]

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
