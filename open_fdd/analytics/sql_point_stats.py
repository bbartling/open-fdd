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

from open_fdd.analytics.point_stats import ANOMALY_ROLES, DIURNAL_ROLES, setpoint_roles
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
            start_ms: int | None, end_ms: int | None, window: int = 0, limit: int = 0) -> str:
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
    point_filter_p = point_filter.replace(" AND s.point_key IN", " AND p.point_key IN")
    return body.format(ts_ms=TS_MS[engine], site_id=_quote(site_id), point_filter=point_filter,
                       point_filter_p=point_filter_p, role_filter=role_filter, window_filter=window_filter,
                       window=int(window), limit=int(limit))


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


# ---- slice 2: role timeseries, anomaly coverage, PID hunting proxy ------------------------------------------------
TIMESERIES_COLUMNS = ("point_key", "equipment_id", "role", "t", "value")
COVERAGE_COLUMNS = ("point_key", "equipment_id", "role", "n", "var_val", "is_short", "is_constant")
PID_COLUMNS = ("point_key", "equipment_id", "role", "n", "avg_val", "var_val", "is_hunting")


def render_role_timeseries_sql(engine: str, roles: Iterable[str], *, limit: int = 5000, site_id: str = DEFAULT_SITE,
                               point_keys: Iterable[str] | None = None, start_ms: int | None = None,
                               end_ms: int | None = None) -> str:
    """Newest first, at most ``limit`` rows (1..100000)."""
    if not 1 <= int(limit) <= 100_000:
        raise ValueError("limit must be 1..100000")
    return _render("role_timeseries", engine, site_id=site_id, point_keys=point_keys, roles=list(roles),
                   start_ms=start_ms, end_ms=end_ms, limit=int(limit))


def render_anomaly_coverage_sql(engine: str, *, window: int = 24, roles: Iterable[str] = ANOMALY_ROLES,
                                site_id: str = DEFAULT_SITE, point_keys: Iterable[str] | None = None,
                                start_ms: int | None = None, end_ms: int | None = None) -> str:
    """``window`` is the z-score window the coverage is judged against (>= 2)."""
    if int(window) < 2:
        raise ValueError("window must be at least 2 samples")
    return _render("anomaly_series_coverage", engine, site_id=site_id, point_keys=point_keys, roles=list(roles),
                   start_ms=start_ms, end_ms=end_ms, window=int(window))


def render_pid_hunting_sql(engine: str, *, site_id: str = DEFAULT_SITE, point_keys: Iterable[str] | None = None,
                           start_ms: int | None = None, end_ms: int | None = None) -> str:
    return _render("pid_hunting_proxy", engine, site_id=site_id, point_keys=point_keys, roles=None,
                   start_ms=start_ms, end_ms=end_ms)


def run_role_timeseries_sql(conn: Any, engine: str, roles: Iterable[str], **kwargs: Any) -> list[dict]:
    out = []
    for row in _fetch(conn, engine, render_role_timeseries_sql(engine, roles, **kwargs)):
        rec = dict(zip(TIMESERIES_COLUMNS, row))
        rec["t"], rec["value"] = int(rec["t"]), float(rec["value"])
        out.append(rec)
    return out


def run_anomaly_coverage_sql(conn: Any, engine: str, **kwargs: Any) -> list[dict]:
    """One dict per bound point of the roles, also with no samples: n, var_val, is_short, is_constant."""
    out = []
    for row in _fetch(conn, engine, render_anomaly_coverage_sql(engine, **kwargs)):
        rec = dict(zip(COVERAGE_COLUMNS, row))
        rec["n"], rec["is_short"], rec["is_constant"] = int(rec["n"]), int(rec["is_short"]), int(rec["is_constant"])
        rec["var_val"] = None if rec["var_val"] is None else float(rec["var_val"])
        out.append(rec)
    return out


def run_pid_hunting_sql(conn: Any, engine: str, **kwargs: Any) -> list[dict]:
    """One dict per PID-role point with >= 12 samples: n, avg_val, var_val, stddev_val, is_hunting."""
    out = []
    for row in _fetch(conn, engine, render_pid_hunting_sql(engine, **kwargs)):
        rec = dict(zip(PID_COLUMNS, row))
        rec["n"], rec["is_hunting"] = int(rec["n"]), int(rec["is_hunting"])
        rec["avg_val"], rec["var_val"] = float(rec["avg_val"]), float(rec["var_val"])
        rec["stddev_val"] = math.sqrt(max(rec["var_val"], 0.0))
        out.append(rec)
    return out
