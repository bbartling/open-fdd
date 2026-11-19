"""SQL BAS vs web outdoor-air statistics (issue #1649): ``sql/analytics/bas_vs_web_oat.sql`` on SQLite, DuckDB or
PostgreSQL. Per equipment: the BAS outdoor-air point against the site's web outdoor-air point, web joined as-of to each
BAS sample, as :func:`open_fdd.analytics.weather_resolver.bas_vs_web_oat_stats`. The packaged copy
``open_fdd/data/bas_vs_web_oat.sql`` is byte-identical to the repo file (a test checks it).
"""

from __future__ import annotations

import math
from importlib import resources
from typing import Any, Iterable

from open_fdd.analytics.sql_anomaly import DEFAULT_SITE, _quote
from open_fdd.analytics.sql_runtime import TS_MS, _inline
from open_fdd.analytics.weather_resolver import BAS_WEB_BAND_C

COLUMNS = ("equipment_id", "n", "bias", "mae", "max_abs", "n_within")


def bas_web_sql_template() -> str:
    return resources.files("open_fdd").joinpath("data/bas_vs_web_oat.sql").read_text(encoding="utf-8")


def render_bas_web_sql(
    engine: str,
    pairs: Iterable[tuple[str, str, str, int]],
    *,
    site_id: str = DEFAULT_SITE,
    band_c: float = BAS_WEB_BAND_C,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> str:
    """``pairs``: (equipment_id, BAS point_key, web point_key, as-of age limit in ms)."""
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}")
    rows = [(e, b, w, int(a)) for e, b, w, a in pairs]
    if any(a < 0 for *_x, a in rows):
        raise ValueError("max_age_ms must be >= 0")
    band = float(band_c)
    if not math.isfinite(band) or band < 0:
        raise ValueError("band_c must be a non-negative number")
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    window_filter = web_window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
        web_window_filter += f" AND w.t >= {int(start_ms)} - w.max_age_ms"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
        web_window_filter += f" AND w.t < {int(end_ms)}"
    body = "\n".join(ln for ln in bas_web_sql_template().splitlines() if not ln.lstrip().startswith("--"))
    return body.format(
        pairs=_inline([("equipment_id", "TEXT"), ("bas_key", "TEXT"), ("web_key", "TEXT"), ("max_age_ms", "INTEGER")],
                      rows),
        ts_ms=TS_MS[engine],
        site_id=_quote(site_id),
        window_filter=window_filter,
        web_window_filter=web_window_filter,
        band=repr(band),
    )


def run_bas_web_sql(conn: Any, engine: str, pairs: Iterable[tuple[str, str, str, int]], **kwargs: Any) -> list[dict]:
    """One dict per equipment with paired samples: n, bias, mae, max_abs, within_band (share)."""
    rows_in = list(pairs)
    if not rows_in:
        return []
    sql = render_bas_web_sql(engine, rows_in, **kwargs)
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        rec = dict(zip(COLUMNS, row))
        rec["n"] = int(rec["n"])
        for k in ("bias", "mae", "max_abs"):
            rec[k] = float(rec[k])
        rec["within_band"] = int(rec.pop("n_within")) / rec["n"]
        out.append(rec)
    return out
