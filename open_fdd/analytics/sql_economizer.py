"""SQL economizer metrics (issue #1649): ``sql/analytics/economizer_metrics.sql`` on SQLite, DuckDB or PostgreSQL.

Per air handler: fan-on hours and samples, identifiable samples (|OAT - RAT| >= the minimum), and the median / mean
absolute MAT residual against the damper mixing model, as the ``metrics`` of
:func:`open_fdd.analytics.core.economizer_free_cooling_diagnostics`. Roles are bound here from the role map (never
point names); the sample math runs in SQL. The packaged copy ``open_fdd/data/economizer_metrics.sql`` is
byte-identical to the repo file (a test checks it). Not ported: the OA-fraction vs damper regression (slope,
intercept, r2) and the per-sample points used for the scatter chart.
"""

from __future__ import annotations

import math
from importlib import resources
from typing import Any, Iterable

from open_fdd.analytics.runtime_intervals import ELAPSED_MAX_GAP_SECONDS
from open_fdd.analytics.si_thresholds import ECON_DIAG_DT_MIN_C
from open_fdd.analytics.sql_anomaly import DEFAULT_SITE, _connect, _quote, create_core, load_core, normalize_engine
from open_fdd.analytics.sql_runtime import TS_MS, _inline

ROLES = ("fan", "oat", "rat", "mat", "damper")
AIR_TYPES = frozenset({"AHU", "RTU"})
COLUMNS = ("equipment_id", "fan_on_ms", "n_fan_on", "n_identifiable", "n_resid", "median_resid", "mae_resid")


def economizer_sql_template() -> str:
    return resources.files("open_fdd").joinpath("data/economizer_metrics.sql").read_text(encoding="utf-8")


def render_economizer_sql(
    engine: str,
    roles: Iterable[tuple[str, str, str]],
    *,
    site_id: str = DEFAULT_SITE,
    dt_min_c: float = ECON_DIAG_DT_MIN_C,
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_gap_seconds: float = ELAPSED_MAX_GAP_SECONDS,
) -> str:
    """``roles``: (equipment_id, role, point_key), role in :data:`ROLES`."""
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}")
    rows = list(roles)
    for _eq, role, _key in rows:
        if role not in ROLES:
            raise ValueError(f"unknown economizer role {role!r}")
    dt = float(dt_min_c)
    gap = float(max_gap_seconds)
    if not math.isfinite(dt) or dt < 0:
        raise ValueError("dt_min_c must be a non-negative number")
    if not math.isfinite(gap) or gap <= 0:
        raise ValueError("max_gap_seconds must be a positive number")
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
    body = "\n".join(ln for ln in economizer_sql_template().splitlines() if not ln.lstrip().startswith("--"))
    return body.format(
        roles=_inline([("equipment_id", "TEXT"), ("role", "TEXT"), ("point_key", "TEXT")], rows),
        ts_ms=TS_MS[engine],
        site_id=_quote(site_id),
        window_filter=window_filter,
        max_gap_ms=int(round(gap * 1000.0)),
        dt_min=repr(dt),
    )


def run_economizer_sql(conn: Any, engine: str, roles: Iterable[tuple[str, str, str]], **kwargs: Any) -> list[dict]:
    rows_in = list(roles)
    if not rows_in:
        return []
    sql = render_economizer_sql(engine, rows_in, **kwargs)
    if normalize_engine(engine) == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        rec = dict(zip(COLUMNS, row))
        for k in ("fan_on_ms", "n_fan_on", "n_identifiable", "n_resid"):
            rec[k] = int(rec[k])
        for k in ("median_resid", "mae_resid"):
            rec[k] = None if rec[k] is None else float(rec[k])
        out.append(rec)
    return out


def _oat_role(mapped, prefer_web_oat: bool) -> str | None:
    """The column pandas ``_econ_resolve_oat`` reads (BAS before web unless ``prefer_web_oat``)."""
    def has(col):
        return col in mapped.columns and mapped[col].notna().any()

    bas = next((c for c in ("outside-air-temp", "bas-outside-air-temp") if has(c)), None)
    web = next((c for c in ("web-outside-air-temp", "oa_t_effective") if has(c)), None)
    if prefer_web_oat and web:
        return web
    return bas or web


def plan_from_frames(frames: dict, role_map: dict, *, prefer_web_oat: bool = False):
    """(roles, core points, core samples, info) for the AHU / RTU frames pandas would assess.

    ``info[equipment_id]`` holds the equipment type and has_damper. An equipment is assessed when it has OAT, RAT and
    MAT columns and a fan role, as in pandas.
    """
    import numpy as np
    import pandas as pd

    from open_fdd.analytics.core import MAPPED_FAN_ROLES, apply_role_map, resolve_equipment_type
    from open_fdd.analytics.role_map import coerce_role_map
    from open_fdd.analytics.site_model import normalize_equipment_type

    role_map = coerce_role_map(role_map, frames)
    roles, points, samples, info = [], [], [], {}
    for eq_id, raw in (frames or {}).items():
        if raw is None or raw.empty or not isinstance(raw.index, pd.DatetimeIndex):
            continue
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        et_n = normalize_equipment_type(et) if et else ""
        if et_n not in AIR_TYPES:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        oat = _oat_role(mapped, prefer_web_oat)
        fans = [r for r in MAPPED_FAN_ROLES if r in mapped.columns and mapped[r].notna().any()]
        if oat is None or "return-air-temp" not in mapped.columns or "mixed-air-temp" not in mapped.columns or not fans:
            continue
        has_damper = "outside-air-damper" in mapped.columns and bool(mapped["outside-air-damper"].notna().any())
        index = pd.DatetimeIndex(mapped.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        ts_ms = (index.tz_convert("UTC").as_unit("ns").asi8 // 1_000_000).astype("int64")
        cols = [(f, "fan") for f in fans] + [(oat, "oat"), ("return-air-temp", "rat"), ("mixed-air-temp", "mat")]
        if has_damper:
            cols.append(("outside-air-damper", "damper"))
        for col, role in cols:
            values = pd.to_numeric(mapped[col], errors="coerce").to_numpy(dtype=float)
            ok = ~np.isnan(values)
            key = f"{eq_id}/{col}"
            roles.append((str(eq_id), role, key))
            points.append({"site_id": DEFAULT_SITE, "point_key": key, "equipment_id": str(eq_id), "role": col})
            samples.extend((DEFAULT_SITE, key, int(t), float(v)) for t, v in zip(ts_ms[ok], values[ok]))
        info[str(eq_id)] = {"equipment_type": et_n, "has_damper": has_damper}
    return roles, points, samples, info


def rows_to_metrics(rows: list[dict], info: dict, *, dt_min_c: float = ECON_DIAG_DT_MIN_C):
    """The query's rows as the metric columns pandas reports (rounded the same way)."""
    import pandas as pd

    out = []
    for r in rows:
        eq = r["equipment_id"]
        out.append(
            {
                "equipment_id": eq,
                "equipment_type": info[eq]["equipment_type"],
                "fan_on_hours": round(r["fan_on_ms"] / 1000.0 / 3600.0, 2),
                "n_fan_on_samples": r["n_fan_on"],
                "n_identifiable": r["n_identifiable"],
                "has_damper": info[eq]["has_damper"],
                "median_mat_resid_f": round(r["median_resid"], 2) if r["median_resid"] is not None else float("nan"),
                "mat_resid_mae_f": round(r["mae_resid"], 2) if r["mae_resid"] is not None else float("nan"),
                "dt_min_f": float(dt_min_c),
            }
        )
    return pd.DataFrame(out)


def economizer_metrics_sql(frames: dict, role_map: dict, *, engine: str = "sqlite", prefer_web_oat: bool = False,
                           dt_min_c: float = ECON_DIAG_DT_MIN_C):
    """Per-AHU economizer metrics computed by the SQL query in-process (the pandas ``metrics`` columns it ports)."""
    roles, points, samples, info = plan_from_frames(frames, role_map, prefer_web_oat=prefer_web_oat)
    rows = []
    if roles:
        conn = _connect(engine)
        try:
            create_core(conn, engine)
            load_core(conn, engine, points, samples)
            rows = run_economizer_sql(conn, engine, roles, dt_min_c=dt_min_c)
        finally:
            conn.close()
    return rows_to_metrics(rows, info, dt_min_c=dt_min_c)


# ---------------------------------------------------------------- per-sample points (#1649: the economizer charts)

POINT_COLUMNS = ("equipment_id", "t", "oat", "rat", "mat", "d_or", "d_mr", "identifiable", "damper_pct", "mat_resid",
                 "oa_frac_pct")


def economizer_points_sql_template() -> str:
    return resources.files("open_fdd").joinpath("data/economizer_points.sql").read_text(encoding="utf-8")


def render_economizer_points_sql(
    engine: str,
    roles: Iterable[tuple[str, str, str]],
    *,
    site_id: str = DEFAULT_SITE,
    dt_min_c: float = ECON_DIAG_DT_MIN_C,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> str:
    """Per-sample economizer points (fan on, OAT and RAT present); same roles and checks as the metrics query."""
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}")
    rows = list(roles)
    for _eq, role, _key in rows:
        if role not in ROLES:
            raise ValueError(f"unknown economizer role {role!r}")
    dt = float(dt_min_c)
    if not math.isfinite(dt) or dt < 0:
        raise ValueError("dt_min_c must be a non-negative number")
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
    body = "\n".join(ln for ln in economizer_points_sql_template().splitlines() if not ln.lstrip().startswith("--"))
    return body.format(
        roles=_inline([("equipment_id", "TEXT"), ("role", "TEXT"), ("point_key", "TEXT")], rows),
        ts_ms=TS_MS[engine],
        site_id=_quote(site_id),
        window_filter=window_filter,
        dt_min=repr(dt),
    )


def run_economizer_points_sql(conn: Any, engine: str, roles: Iterable[tuple[str, str, str]], **kwargs: Any) -> list[dict]:
    rows_in = list(roles)
    if not rows_in:
        return []
    sql = render_economizer_points_sql(engine, rows_in, **kwargs)
    if normalize_engine(engine) == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        rec = dict(zip(POINT_COLUMNS, row))
        rec["t"] = int(rec["t"]) if not hasattr(rec["t"], "timestamp") else int(rec["t"].timestamp() * 1000)
        rec["identifiable"] = bool(rec["identifiable"])
        for k in ("oat", "rat", "mat", "d_or", "d_mr", "damper_pct", "mat_resid", "oa_frac_pct"):
            rec[k] = None if rec[k] is None else float(rec[k])
        out.append(rec)
    return out
