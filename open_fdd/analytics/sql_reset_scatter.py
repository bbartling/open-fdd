"""SQL reset scatters (issue #1757): ``sql/analytics/reset_scatter.sql`` on SQLite, DuckDB or PostgreSQL over the v5 SI
core. Each sample of a plotted point (SAT, HW / CHW / CW supply) is paired as-of with outdoor air, with the same
pairing as :func:`open_fdd.analytics.weather_resolver.bas_vs_web_pairs`, which is its pandas twin (see
:func:`reset_scatter_pairs`). The packaged copy ``open_fdd/data/reset_scatter.sql`` is byte-identical to the repo file.
The SQLite driver is the standard library; DuckDB needs ``duckdb``, PostgreSQL ``psycopg``.
"""

from __future__ import annotations

from importlib import resources
from typing import Any, Iterable

from open_fdd.analytics.sql_anomaly import DEFAULT_SITE, _quote
from open_fdd.analytics.sql_runtime import TS_MS, _inline

COLUMNS = ("scatter_id", "equipment_id", "t", "x", "y")


def reset_scatter_sql_template() -> str:
    return resources.files("open_fdd").joinpath("data/reset_scatter.sql").read_text(encoding="utf-8")


def render_reset_scatter_sql(engine: str, pairs: Iterable[tuple[str, str, str, str, int]], *,
                             site_id: str = DEFAULT_SITE, start_ms: int | None = None,
                             end_ms: int | None = None) -> str:
    """``pairs``: (scatter_id, equipment_id, y point_key, x point_key, as-of age limit in ms)."""
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}")
    rows = [(str(s), str(e), str(y), str(x), int(a)) for s, e, y, x, a in pairs]
    if any(a < 0 for *_r, a in rows):
        raise ValueError("max_age_ms must be >= 0")
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError("scatter_id must be unique")
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    window_filter = x_window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
        x_window_filter += f" AND w.t >= {int(start_ms)} - w.max_age_ms"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
        x_window_filter += f" AND w.t < {int(end_ms)}"
    body = "\n".join(ln for ln in reset_scatter_sql_template().splitlines() if not ln.lstrip().startswith("--"))
    return body.format(
        pairs=_inline([("scatter_id", "TEXT"), ("equipment_id", "TEXT"), ("y_key", "TEXT"), ("x_key", "TEXT"),
                       ("max_age_ms", "INTEGER")], rows),
        ts_ms=TS_MS[engine], site_id=_quote(site_id), window_filter=window_filter, x_window_filter=x_window_filter)


def run_reset_scatter_sql(conn: Any, engine: str, pairs: Iterable[tuple[str, str, str, str, int]],
                          **kwargs: Any) -> list[dict]:
    """One dict per paired sample: scatter_id, equipment_id, t (epoch ms), x (outdoor air), y (plotted point)."""
    rows_in = list(pairs)
    if not rows_in:
        return []
    sql = render_reset_scatter_sql(engine, rows_in, **kwargs)
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        rec = dict(zip(COLUMNS, row))
        rec["t"], rec["x"], rec["y"] = int(rec["t"]), float(rec["x"]), float(rec["y"])
        out.append(rec)
    return out


def reset_scatter_pairs(y, x, *, max_age_seconds: float | None = None):
    """pandas twin for one scatter: the y samples paired as-of with x (columns t, x, y). Same pairing as
    :func:`open_fdd.analytics.weather_resolver.bas_vs_web_pairs` (y plays the BAS role, x the web role)."""
    from open_fdd.analytics.weather_resolver import bas_vs_web_pairs

    p = bas_vs_web_pairs(y, x, max_age_seconds=max_age_seconds)
    return p.rename(columns={"bas": "y", "web": "x"}).loc[:, ["t", "x", "y"]]
