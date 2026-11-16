"""SQL rolling z-score (issue #1649): ``sql/analytics/anomaly_zscore.sql`` on SQLite, DuckDB or PostgreSQL.

The query reads the v5 SI core (``fdd.point`` + ``fdd.input_sample``) and returns, per point and sample, the same
flags as :func:`open_fdd.analytics.anomaly.detectors.rolling_zscore_flags` on that point's non-NULL series. The
packaged copy ``open_fdd/data/anomaly_zscore.sql`` is byte-identical to the repo file (a test checks it).

Use :func:`zscore_flags_sql` for a wide pandas frame (it builds an in-process SQLite or DuckDB core and runs the
query; ``open-fdd-anomaly screen --engine sql`` uses it), or :func:`run_zscore_sql` on a database that already
exposes ``fdd.point`` and ``fdd.input_sample`` (Open-FDD Full / Timescale, a downstream PostgreSQL store).
Standard library only for SQLite; DuckDB needs ``duckdb``, PostgreSQL needs ``psycopg``.
"""

from __future__ import annotations

import math
from importlib import resources
from typing import Any, Iterable, Sequence

ENGINES = ("sqlite", "duckdb", "postgres")
DEFAULT_SITE = "local"


def zscore_sql_template() -> str:
    """The packaged SQL template (with ``{placeholders}``)."""
    return resources.files("open_fdd").joinpath("data/anomaly_zscore.sql").read_text(encoding="utf-8")


def _quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def render_zscore_sql(
    window: int,
    threshold: float = 3.0,
    *,
    site_id: str = DEFAULT_SITE,
    point_keys: Iterable[str] | None = None,
) -> str:
    """Render the query with checked literals (no string from the caller reaches SQL unquoted)."""
    window = int(window)
    if window < 2:
        raise ValueError("window must be at least 2 samples")
    threshold = float(threshold)
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold must be a positive number")
    keys = list(point_keys) if point_keys is not None else []
    point_filter = ""
    if keys:
        point_filter = " AND s.point_key IN (" + ", ".join(_quote(k) for k in keys) + ")"
    sql = zscore_sql_template()
    lines = [ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")]
    body = "\n".join(lines)
    return body.format(
        site_id=_quote(site_id),
        point_filter=point_filter,
        window=window,
        window_minus_1=window - 1,
        threshold=repr(threshold),
    )


COLUMNS = ("point_key", "equipment_id", "role", "ts", "value", "z2", "is_anomaly", "is_event")


def create_core(conn: Any, engine: str) -> None:
    """Create a minimal ``fdd.point`` + ``fdd.input_sample`` (view over ``fdd.sample_store``) on a fresh connection.

    SQLite gets an attached in-memory database named ``fdd``. Only the columns the analytics read are created; the
    full core schema is ``sql/fdd/schema/core.sql``.
    """
    if engine == "sqlite":
        conn.execute("ATTACH DATABASE ':memory:' AS fdd")
        conn.execute("CREATE TABLE fdd.point (site_id TEXT NOT NULL, point_key TEXT NOT NULL, equipment_id TEXT, "
                     "role TEXT, PRIMARY KEY (site_id, point_key))")
        conn.execute("CREATE TABLE fdd.sample_store (site_id TEXT NOT NULL, point_key TEXT NOT NULL, ts INTEGER NOT NULL, "
                     "value REAL)")
        conn.execute("CREATE VIEW fdd.input_sample AS SELECT site_id, point_key, ts, value FROM sample_store "
                     "WHERE value IS NOT NULL")
        return
    ts_type = "TIMESTAMPTZ" if engine == "postgres" else "TIMESTAMP"
    for stmt in (
        "CREATE SCHEMA IF NOT EXISTS fdd",
        "CREATE TABLE fdd.point (site_id TEXT NOT NULL, point_key TEXT NOT NULL, equipment_id TEXT, role TEXT, "
        "PRIMARY KEY (site_id, point_key))",
        f"CREATE TABLE fdd.sample_store (site_id TEXT NOT NULL, point_key TEXT NOT NULL, ts {ts_type} NOT NULL, "
        "value DOUBLE PRECISION)",
        "CREATE VIEW fdd.input_sample AS SELECT site_id, point_key, ts, value FROM fdd.sample_store "
        "WHERE value IS NOT NULL",
    ):
        conn.execute(stmt)


def load_core(
    conn: Any,
    engine: str,
    points: Sequence[dict],
    samples: Sequence[tuple],
) -> None:
    """Insert ``points`` (dicts with site_id, point_key, equipment_id, role) and ``samples``
    (``(site_id, point_key, ts_ms_utc, value)``). Timestamps are stored as integer ms on SQLite, timestamps elsewhere."""
    point_rows = [(p["site_id"], p["point_key"], p.get("equipment_id"), p.get("role")) for p in points]
    if engine == "sqlite":
        conn.executemany("INSERT INTO fdd.point VALUES (?, ?, ?, ?)", point_rows)
        conn.executemany("INSERT INTO fdd.sample_store VALUES (?, ?, ?, ?)", [tuple(s) for s in samples])
        return
    if engine == "duckdb":
        import pandas as pd

        pts = pd.DataFrame(point_rows, columns=["site_id", "point_key", "equipment_id", "role"])
        smp = pd.DataFrame(list(samples), columns=["site_id", "point_key", "ts", "value"])
        smp["ts"] = pd.to_datetime(smp["ts"], unit="ms")
        smp["value"] = smp["value"].astype(float)
        conn.register("_ofdd_points", pts)
        conn.register("_ofdd_samples", smp)
        conn.execute("INSERT INTO fdd.point SELECT * FROM _ofdd_points")
        conn.execute("INSERT INTO fdd.sample_store SELECT * FROM _ofdd_samples")
        conn.unregister("_ofdd_points")
        conn.unregister("_ofdd_samples")
        return
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO fdd.point VALUES (%s, %s, %s, %s)", point_rows)
            with cur.copy("COPY fdd.sample_store (site_id, point_key, ts, value) FROM STDIN") as copy:
                for site, key, ts_ms, value in samples:
                    copy.write_row((site, key, _pg_ts(ts_ms), value))
        return
    raise ValueError(f"unknown engine {engine!r}; choose from {', '.join(ENGINES)}")


def _pg_ts(ts_ms: int):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)


def run_zscore_sql(
    conn: Any,
    engine: str,
    *,
    window: int,
    threshold: float = 3.0,
    site_id: str = DEFAULT_SITE,
    point_keys: Iterable[str] | None = None,
) -> list[dict]:
    """Run the query on a connection that exposes the core; return one dict per scored sample (:data:`COLUMNS`)."""
    sql = render_zscore_sql(window, threshold, site_id=site_id, point_keys=point_keys)
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [dict(zip(COLUMNS, row)) for row in rows]


def _connect(engine: str):
    if engine == "sqlite":
        import sqlite3

        return sqlite3.connect(":memory:")
    if engine == "duckdb":
        import duckdb

        return duckdb.connect(":memory:")
    raise ValueError("zscore_flags_sql runs in-process on sqlite or duckdb")


def zscore_flags_sql(frame, *, window: int, threshold: float = 3.0, engine: str = "sqlite"):
    """Flags for every numeric column of a time-indexed wide frame, computed by the SQL query.

    Returns a boolean frame shaped like ``frame`` (False where a value is missing, as in the pandas detector when the
    series is restricted to its non-missing samples).
    """
    import pandas as pd

    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    ts_ms = (index.tz_convert("UTC").as_unit("ns").asi8 // 1_000_000).astype("int64")
    points, samples = [], []
    keys = {}
    for i, column in enumerate(frame.columns):
        values = pd.to_numeric(frame[column], errors="coerce")
        key = f"p{i}"
        keys[key] = column
        points.append({"site_id": DEFAULT_SITE, "point_key": key, "equipment_id": None, "role": str(column)})
        ok = values.notna().to_numpy()
        samples.extend((DEFAULT_SITE, key, int(t), float(v)) for t, v in zip(ts_ms[ok], values.to_numpy()[ok]))
    conn = _connect(engine)
    try:
        create_core(conn, engine)
        load_core(conn, engine, points, samples)
        rows = run_zscore_sql(conn, engine, window=window, threshold=threshold)
    finally:
        conn.close()
    out = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    pos = {int(t): j for j, t in enumerate(ts_ms)}
    for row in rows:
        if not row["is_anomaly"]:
            continue
        t = row["ts"]
        t_ms = int(t) if engine == "sqlite" else int(pd.Timestamp(t).tz_localize("UTC").value // 1_000_000) \
            if pd.Timestamp(t).tzinfo is None else int(pd.Timestamp(t).value // 1_000_000)
        out.iat[pos[t_ms], frame.columns.get_loc(keys[row["point_key"]])] = True
    return out
