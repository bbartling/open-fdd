"""Motor / fan / pump weekly runtime from BRICK model + PyArrow historian (no pandas)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

MOTOR_BRICK_HINTS = (
    "Fan",
    "Pump",
    "Motor",
    "Compressor",
    "Blower",
)

RUN_STATUS_BRICK = frozenset(
    {
        "Fan_Status",
        "Fan_Status_Sensor",
        "Pump_Status",
        "Pump_Status_Sensor",
        "Motor_Status",
        "On_Off_Status",
        "Run_Status",
    }
)

RUN_SPEED_BRICK = frozenset(
    {
        "Fan_Speed_Command",
        "Fan_Speed_Sensor",
        "Supply_Fan_Speed_Sensor",
        "Return_Fan_Speed_Sensor",
        "VFD_Speed_Command",
        "VFD_Speed_Sensor",
        "Pump_Speed_Command",
        "Pump_Speed_Sensor",
    }
)


def _is_motor_point(pt: dict[str, Any]) -> bool:
    brick = str(pt.get("brick_type") or "").strip()
    if not brick:
        return False
    if brick in RUN_STATUS_BRICK or brick in RUN_SPEED_BRICK:
        return True
    return any(h in brick for h in MOTOR_BRICK_HINTS)


def _run_threshold(brick: str) -> float:
    if brick in RUN_STATUS_BRICK or "Status" in brick:
        return 0.5
    return 0.01


def motors_from_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Return motor/fan/pump points from SPARQL model tree."""
    from .trend_charts import historian_column_for_point

    rows: list[dict[str, Any]] = []
    equipment_by_id = {
        str(e.get("id") or e.get("equipment_id") or ""): e
        for e in (tree.get("equipment") or [])
        if isinstance(e, dict)
    }
    for pt in tree.get("points") or []:
        if not isinstance(pt, dict) or not _is_motor_point(pt):
            continue
        col = historian_column_for_point(pt)
        if not col:
            continue
        eid = str(pt.get("equipment_id") or "")
        eq = equipment_by_id.get(eid) or {}
        brick = str(pt.get("brick_type") or "")
        rows.append(
            {
                "point_id": str(pt.get("id") or ""),
                "column": col,
                "label": str(pt.get("name") or col),
                "brick_type": brick,
                "equipment_id": eid,
                "equipment_name": str(eq.get("name") or eid),
                "threshold": _run_threshold(brick),
                "signal_kind": "status" if brick in RUN_STATUS_BRICK else "speed",
            }
        )
    return rows


def _hours_on_from_table(table, col: str, *, threshold: float) -> tuple[float, int]:
    import pyarrow as pa
    import pyarrow.compute as pc

    if table is None or table.num_rows < 2 or col not in table.column_names:
        return 0.0, 0
    ts_col = table.column("timestamp")
    if pa.types.is_string(ts_col.type) or pa.types.is_large_string(ts_col.type):
        ts = pc.cast(ts_col, pa.timestamp("us", tz="UTC"))
    else:
        ts = ts_col
    vals = table.column(col).to_pylist()
    ts_list = ts.to_pylist()
    total_h = 0.0
    samples = 0
    for i in range(1, len(ts_list)):
        t0, t1 = ts_list[i - 1], ts_list[i]
        if t0 is None or t1 is None:
            continue
        if isinstance(t0, datetime) and isinstance(t1, datetime):
            dt_h = (t1 - t0).total_seconds() / 3600.0
        else:
            continue
        if dt_h <= 0 or dt_h > 24:
            continue
        v = vals[i - 1]
        try:
            on = v is not None and float(v) >= threshold
        except (TypeError, ValueError):
            on = False
        if on:
            total_h += dt_h
            samples += 1
    return round(total_h, 2), samples


def weekly_motor_runtime(
    site_id: str,
    tree: dict[str, Any] | None = None,
    *,
    hours: int = 168,
    source: str = "bacnet",
) -> list[dict[str, Any]]:
    """Estimated motor run-hours over lookback window (defaults to 1 week)."""
    from ..feather_store import FeatherStore
    from ..model_sparql import query_model_tree

    if tree is None:
        try:
            tree = query_model_tree()
        except Exception:
            tree = {"points": [], "equipment": []}

    motors = motors_from_tree(tree)
    if not motors:
        return []

    cols = list(dict.fromkeys(m["column"] for m in motors))
    store = FeatherStore()
    read_cols = ["timestamp", *cols]
    table = store.read_site_table(site_id, source=source, columns=read_cols)
    if table is None or table.num_rows == 0:
        for src in ("bacnet", "niagara_baskstream", "modbus"):
            if src == source:
                continue
            table = store.read_site_table(site_id, source=src, columns=read_cols)
            if table is not None and table.num_rows > 0:
                break

    if table is not None and table.num_rows > 0 and "timestamp" in table.column_names:
        import pyarrow as pa
        import pyarrow.compute as pc

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
        ts_col = table.column("timestamp")
        if pa.types.is_string(ts_col.type) or pa.types.is_large_string(ts_col.type):
            parsed = pc.cast(ts_col, pa.timestamp("us", tz="UTC"))
        else:
            parsed = ts_col
        mask = pc.greater_equal(parsed, pa.scalar(cutoff, type=parsed.type))
        filtered = table.filter(mask)
        if filtered.num_rows > 0:
            table = filtered

    out: list[dict[str, Any]] = []
    for m in motors:
        col = m["column"]
        run_h, samples = _hours_on_from_table(table, col, threshold=float(m["threshold"]))
        out.append(
            {
                **m,
                "runtime_hours": run_h,
                "samples_on": samples,
                "lookback_hours": hours,
                "weekly_hours_est": run_h if hours >= 168 else round(run_h * (168 / max(hours, 1)), 2),
            }
        )
    out.sort(key=lambda r: (-float(r.get("runtime_hours") or 0), r.get("equipment_name") or ""))
    return out
