"""SQL weekly motor run hours (issue #1649): ``sql/analytics/motor_weekly_runtime.sql`` on SQLite, DuckDB or PostgreSQL.

The query reads the v5 SI core (``fdd.point`` + ``fdd.input_sample``) and returns, per equipment, motor role and UTC
week, the same run hours as :func:`open_fdd.analytics.core.motor_run_hours_weekly` on that motor point's samples. The
packaged copy ``open_fdd/data/motor_weekly_runtime.sql`` is byte-identical to the repo file (a test checks it).

Use :func:`run_runtime_sql` on a database that already exposes the core (Open-FDD Full / Timescale), or
:func:`motor_run_hours_weekly_sql` for pandas frames plus a role map (it builds an in-process SQLite or DuckDB core and
returns the columns of the pandas function, so the two can be compared row by row).
"""

from __future__ import annotations

import math
from importlib import resources
from typing import Any, Iterable

from open_fdd.analytics.runtime_intervals import ELAPSED_MAX_GAP_SECONDS
from open_fdd.analytics.sql_anomaly import DEFAULT_SITE, ENGINES, _connect, _quote, create_core, load_core

#: ts -> integer epoch milliseconds, per engine (SQLite stores integer ms; the others store timestamps).
TS_MS = {
    "sqlite": "s.ts",
    "duckdb": "epoch_ms(s.ts)",
    "postgres": "CAST(EXTRACT(EPOCH FROM s.ts) * 1000 AS BIGINT)",
}

#: SQL role -> pandas analytics role (the hyphenated names used by ``open_fdd.analytics.core``).
MOTOR_ROLES = {
    "fan_status": "fan-status",
    "fan_cmd": "fan-cmd",
    "pump_status": "pump-status",
    "pump_cmd": "pump-cmd",
    "chw_pump_status": "chw-pump-status",
    "chw_pump_cmd": "chw-pump-cmd",
    "hw_pump_cmd": "hw-pump-cmd",
}

#: Equipment types whose first pump signal is reported as the chiller's run, and the order that picks it.
CHILLER_TYPES = {"CHW_PLANT", "CHILLER"}
CHILLER_RUN_ORDER = ("chw-pump-status", "pump-status", "chw-pump-cmd", "pump-cmd")

COLUMNS = ("equipment_id", "signal", "motor_family", "week_start_ms", "run_hours", "n_samples", "partial_week",
           "avg_oat_c")

#: Outdoor-air roles, in the order pandas resolves them (web weather before BAS).
OAT_ROLES = ("web-outside-air-temp", "bas-outside-air-temp", "outside-air-temp")


def _inline(columns: list[tuple[str, str]], rows: list[tuple]) -> str:
    """A typed inline table as SELECT ... UNION ALL ...; zero rows render as a typed empty SELECT.

    Strings are quoted, integers cast, floats must be finite: no caller text reaches SQL unquoted.
    """

    def lit(value, sql_type):
        if value is None:
            return f"CAST(NULL AS {sql_type})"
        if sql_type == "TEXT":
            return _quote(value)
        if sql_type == "INTEGER":
            return str(int(value))
        v = float(value)
        if not math.isfinite(v):
            raise ValueError("inline numbers must be finite")
        return f"CAST({v!r} AS DOUBLE PRECISION)"

    if not rows:
        cols = ", ".join(f"{lit(None, t)} AS {c}" for c, t in columns)
        return f"  SELECT {cols} WHERE 1 = 0"
    return "\n  UNION ALL\n".join(
        "  SELECT " + ", ".join(f"{lit(v, t)} AS {c}" for v, (c, t) in zip(row, columns)) for row in rows
    )


def runtime_sql_template() -> str:
    """The packaged SQL template (with ``{placeholders}``)."""
    return resources.files("open_fdd").joinpath("data/motor_weekly_runtime.sql").read_text(encoding="utf-8")


def render_runtime_sql(
    engine: str,
    *,
    site_id: str = DEFAULT_SITE,
    equipment_ids: Iterable[str] | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_gap_seconds: float = ELAPSED_MAX_GAP_SECONDS,
    oats: Iterable[tuple[str, str]] = (),
) -> str:
    """Render the query with checked literals (no string from the caller reaches SQL unquoted).

    ``start_ms`` / ``end_ms`` bound the samples read (UTC epoch ms, end exclusive); an interval is only measured
    between samples inside the window. ``oats`` is (equipment_id, point_key) of each equipment's outdoor-air point;
    without one, ``avg_oat_c`` is NULL.
    """
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}; choose from {', '.join(ENGINES)}")
    gap = float(max_gap_seconds)
    if not math.isfinite(gap) or gap <= 0:
        raise ValueError("max_gap_seconds must be a positive number")
    eqs = list(equipment_ids) if equipment_ids is not None else []
    equipment_filter = ""
    if eqs:
        equipment_filter = "\n    AND p.equipment_id IN (" + ", ".join(_quote(e) for e in eqs) + ")"
    window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    sql = runtime_sql_template()
    body = "\n".join(ln for ln in sql.splitlines() if not ln.lstrip().startswith("--"))
    return body.format(
        site_id=_quote(site_id),
        equipment_filter=equipment_filter,
        window_filter=window_filter,
        ts_ms=TS_MS[engine],
        max_gap_ms=int(round(gap * 1000.0)),
        oats=_inline([("equipment_id", "TEXT"), ("point_key", "TEXT")], list(oats)),
    )


def run_runtime_sql(conn: Any, engine: str, **kwargs: Any) -> list[dict]:
    """Run the query on a connection that exposes the core; one dict per (equipment, signal, week) (:data:`COLUMNS`)."""
    sql = render_runtime_sql(engine, **kwargs)
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        rec = dict(zip(COLUMNS, row))
        rec["week_start_ms"] = int(rec["week_start_ms"])
        rec["run_hours"] = float(rec["run_hours"])
        rec["n_samples"] = int(rec["n_samples"])
        rec["partial_week"] = bool(rec["partial_week"])
        rec["avg_oat_c"] = None if rec["avg_oat_c"] is None else float(rec["avg_oat_c"])
        out.append(rec)
    return out


def _core_from_frames(frames: dict, role_map: dict) -> tuple[list[dict], list[tuple], list[tuple]]:
    """Points, samples and (equipment_id, OAT point_key) for the bound motor and outdoor-air roles of each frame.

    Missing values are not samples. An equipment's OAT point is its first bound role in :data:`OAT_ROLES`.
    """
    import numpy as np
    import pandas as pd

    from open_fdd.analytics.core import apply_role_map
    from open_fdd.analytics.role_map import coerce_role_map

    role_map = coerce_role_map(role_map, frames)
    points: list[dict] = []
    samples: list[tuple] = []
    oats: list[tuple] = []
    for eq_id, raw in frames.items():
        if raw is None or raw.empty or not isinstance(raw.index, pd.DatetimeIndex):
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        index = pd.DatetimeIndex(mapped.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        ts_ms = (index.tz_convert("UTC").as_unit("ns").asi8 // 1_000_000).astype("int64")

        def add(role: str, sql_role: str) -> str | None:
            if role not in mapped.columns:
                return None
            values = pd.to_numeric(mapped[role], errors="coerce").to_numpy(dtype=float)
            ok = ~np.isnan(values)
            if not ok.any():
                return None
            key = f"{eq_id}/{sql_role}"
            points.append({"site_id": DEFAULT_SITE, "point_key": key, "equipment_id": str(eq_id), "role": sql_role})
            samples.extend((DEFAULT_SITE, key, int(t), float(v)) for t, v in zip(ts_ms[ok], values[ok]))
            return key

        has_motor = False
        for sql_role, role in MOTOR_ROLES.items():
            has_motor = (add(role, sql_role) is not None) or has_motor
        if has_motor:
            for role in OAT_ROLES:
                key = add(role, role.replace("-", "_"))
                if key is not None:
                    oats.append((str(eq_id), key))
                    break
    return points, samples, oats


def motor_run_hours_weekly_sql(frames: dict, role_map: dict, *, engine: str = "sqlite"):
    """Weekly motor run hours computed by the SQL query, with the columns of ``motor_run_hours_weekly``.

    ``plant_group`` and ``label`` come from the same equipment metadata helpers the pandas function uses.
    ``avg_oat_c`` uses the frame's own outdoor-air column (web, else BAS); a separate ``weather`` frame is not read.
    """
    import pandas as pd

    from open_fdd.analytics.core import (
        _equipment_plant_group,
        _fallback_plant_group,
        resolve_equipment_type,
    )
    from open_fdd.analytics.role_map import coerce_role_map

    role_map = coerce_role_map(role_map, frames)
    points, samples, oats = _core_from_frames(frames, role_map)
    conn = _connect(engine)
    try:
        create_core(conn, engine)
        if points:
            load_core(conn, engine, points, samples)
        rows = run_runtime_sql(conn, engine, oats=oats) if points else []
    finally:
        conn.close()
    # A chilled-water plant or chiller reports its first pump signal as the chiller's run (as plant discovery does).
    signals_by_eq: dict[str, set[str]] = {}
    for r in rows:
        signals_by_eq.setdefault(r["equipment_id"], set()).add(MOTOR_ROLES[r["signal"]])
    chiller_signal: dict[str, str] = {}
    for eq_id, signals in signals_by_eq.items():
        if resolve_equipment_type(eq_id, df=frames.get(eq_id), role_map=role_map) in CHILLER_TYPES:
            first = next((s for s in CHILLER_RUN_ORDER if s in signals), None)
            if first:
                chiller_signal[eq_id] = first
    out = []
    for r in rows:
        eq_id = r["equipment_id"]
        raw = frames.get(eq_id)
        role = MOTOR_ROLES[r["signal"]]
        kind = "fan" if r["motor_family"] == "fan" else "pump"
        if chiller_signal.get(eq_id) == role:
            kind = "chiller"
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        plant = _equipment_plant_group(eq_id, et, df=raw, role_map=role_map) or _fallback_plant_group(role, kind)
        week = pd.Timestamp(r["week_start_ms"], unit="ms")
        out.append(
            {
                "week_start": week,
                "week_label": week.strftime("%Y-%m-%d"),
                "equipment_id": eq_id,
                "signal": role,
                "motor_kind": kind,
                "plant_group": plant,
                "label": f"{eq_id} · {role}",
                "hours": round(r["run_hours"], 2),
                "avg_oat_c": r["avg_oat_c"],
                "partial_week": r["partial_week"],
            }
        )
    cols = ["week_start", "week_label", "equipment_id", "signal", "motor_kind", "plant_group", "label", "hours",
            "avg_oat_c", "partial_week"]
    return pd.DataFrame(out, columns=cols)
