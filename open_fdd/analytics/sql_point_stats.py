"""SQL per-point statistics (issue #1757): ``sql/analytics/sensor_stats.sql``, ``diurnal_hourly.sql`` and
``setpoints_latest.sql`` on SQLite, DuckDB or PostgreSQL, over the v5 SI core (``fdd.point`` + ``fdd.input_sample``).
They return the same numbers as the pandas twins in :mod:`open_fdd.analytics.point_stats`. The packaged copies in
``open_fdd/data/`` are byte-identical to the repo files (a test checks it). Standard library only for SQLite.
"""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any, Iterable

from open_fdd.analytics.point_stats import DIURNAL_ROLES, setpoint_roles
from open_fdd.analytics.sql_anomaly import DEFAULT_SITE, _quote
from open_fdd.analytics.sql_runtime import TS_MS

STATS_COLUMNS = ("point_key", "equipment_id", "role", "n", "min_val", "max_val", "avg_val", "var_val", "first_ms",
                 "last_ms")
DIURNAL_COLUMNS = ("point_key", "equipment_id", "role", "hour_utc", "avg_val", "n")
SETPOINT_COLUMNS = ("point_key", "equipment_id", "role", "t", "value")


def template(name: str) -> str:
    """The packaged SQL template ``open_fdd/data/<name>.sql`` (with ``{placeholders}``)."""
    return resources.files("open_fdd").joinpath(f"data/{name}.sql").read_text(encoding="utf-8")


def _render(name: str, engine: str, *, site_id: str, point_keys: Iterable[str] | None, roles: Iterable[str] | None,
            start_ms: int | None, end_ms: int | None) -> str:
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}")
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    keys = list(point_keys or [])
    point_filter = (" AND s.point_key IN (" + ", ".join(_quote(k) for k in keys) + ")") if keys else ""
    role_filter = ""
    if roles is not None:
        rl = list(roles)
        role_filter = (" AND p.role IN (" + ", ".join(_quote(r) for r in rl) + ")") if rl else " AND 1 = 0"
    window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
    body = "\n".join(ln for ln in template(name).splitlines() if not ln.lstrip().startswith("--"))
    return body.format(ts_ms=TS_MS[engine], site_id=_quote(site_id), point_filter=point_filter,
                       role_filter=role_filter, window_filter=window_filter)


def render_sensor_stats_sql(engine: str, *, site_id: str = DEFAULT_SITE, point_keys: Iterable[str] | None = None,
                            start_ms: int | None = None, end_ms: int | None = None) -> str:
    return _render("sensor_stats", engine, site_id=site_id, point_keys=point_keys, roles=None, start_ms=start_ms,
                   end_ms=end_ms)


def render_diurnal_sql(engine: str, *, site_id: str = DEFAULT_SITE, point_keys: Iterable[str] | None = None,
                       roles: Iterable[str] | None = DIURNAL_ROLES, start_ms: int | None = None,
                       end_ms: int | None = None) -> str:
    """``roles=None`` = every role."""
    return _render("diurnal_hourly", engine, site_id=site_id, point_keys=point_keys, roles=roles, start_ms=start_ms,
                   end_ms=end_ms)


def default_setpoint_roles() -> list[str]:
    """Every role in the packaged role map ending in ``_sp`` or ``_setpoint``."""
    return setpoint_roles(json.loads(resources.files("open_fdd").joinpath("data/role_map.json").read_text("utf-8")))


def render_setpoints_sql(engine: str, *, site_id: str = DEFAULT_SITE, point_keys: Iterable[str] | None = None,
                         roles: Iterable[str] | None = None, start_ms: int | None = None,
                         end_ms: int | None = None) -> str:
    """``roles=None`` = :func:`default_setpoint_roles`."""
    return _render("setpoints_latest", engine, site_id=site_id, point_keys=point_keys,
                   roles=default_setpoint_roles() if roles is None else roles, start_ms=start_ms, end_ms=end_ms)


def _fetch(conn: Any, engine: str, sql: str) -> list[tuple]:
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()
    return conn.execute(sql).fetchall()


def run_sensor_stats_sql(conn: Any, engine: str, **kwargs: Any) -> list[dict]:
    """One dict per point: n, min_val, max_val, avg_val, stddev_val (sample; None for one sample), first_ms, last_ms."""
    out = []
    for row in _fetch(conn, engine, render_sensor_stats_sql(engine, **kwargs)):
        rec = dict(zip(STATS_COLUMNS, row))
        var = rec.pop("var_val")
        rec["stddev_val"] = None if var is None else math.sqrt(max(float(var), 0.0))
        for k in ("min_val", "max_val", "avg_val"):
            rec[k] = float(rec[k])
        for k in ("n", "first_ms", "last_ms"):
            rec[k] = int(rec[k])
        out.append(rec)
    return out


def run_diurnal_sql(conn: Any, engine: str, **kwargs: Any) -> list[dict]:
    """One dict per point and UTC hour: avg_val, n."""
    out = []
    for row in _fetch(conn, engine, render_diurnal_sql(engine, **kwargs)):
        rec = dict(zip(DIURNAL_COLUMNS, row))
        rec["hour_utc"], rec["n"], rec["avg_val"] = int(rec["hour_utc"]), int(rec["n"]), float(rec["avg_val"])
        out.append(rec)
    return out


def run_setpoints_sql(conn: Any, engine: str, **kwargs: Any) -> list[dict]:
    """One dict per setpoint point: the last sample in the window (t = epoch ms, value)."""
    out = []
    for row in _fetch(conn, engine, render_setpoints_sql(engine, **kwargs)):
        rec = dict(zip(SETPOINT_COLUMNS, row))
        rec["t"], rec["value"] = int(rec["t"]), float(rec["value"])
        out.append(rec)
    return out
