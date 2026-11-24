"""Portable SQL for the fault-confidence screen.

The heavy work (turning millions of rule rows into episodes and per-rule totals) runs inside the database with
plain SQL that works on SQLite (3.25+), DuckDB, PostgreSQL and TimescaleDB: CTEs, ``ROW_NUMBER()`` window functions,
``CASE``, ``COUNT``/``SUM``/``AVG``/``MIN``/``MAX``. No ``SQRT``, ``STDDEV``, ``FILTER`` or date arithmetic is used, so
the same text runs everywhere. Only the episode and totals rows come back to Python.

Two input layouts are supported:

* ``results`` (default): Open-FDD ``fdd.rule_result`` windows (``equipment_id``, ``rule_id``, ``subject_key``,
  ``window_start``, ``window_end``, ``status``, ``fault_hours``, ``covered_hours``). Consecutive FAULT windows of one
  (equipment, rule, subject) form an episode.
* ``flags``: one row per rule evaluation sample (``timestamp``, ``equipment_id``, ``rule_id``, ``flag`` and optional
  ``value``, ``threshold``, ``running``). Consecutive flagged samples form an episode.

Column and table names can be remapped for any schema. Names are validated as SQL identifiers; values are never
interpolated except the configured status strings, which are quoted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

RESULT_COLUMNS = (
    "site_id", "equipment_id", "rule_id", "subject_key", "window_start", "window_end", "status",
    "fault_hours", "covered_hours",
)
FLAG_COLUMNS = ("site_id", "equipment_id", "rule_id", "timestamp", "flag", "value", "threshold", "running")
HISTORY_COLUMNS = ("site_id", "point_key", "ts", "value", "equipment_id", "kind")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_NULL = "CAST(NULL AS DOUBLE PRECISION)"
FLAG_TRUE_TEXT = ("1", "1.0", "true", "t", "yes", "y", "fault", "on")


def ident(name: str) -> str:
    """Validate a table or column name (optionally ``schema.name``)."""
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(f"not a plain SQL identifier: {name!r}")
    return name


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@dataclass
class SourceMap:
    """Where the rule output lives and what its columns are called.

    ``columns`` maps the screen's names (``RESULT_COLUMNS`` or ``FLAG_COLUMNS``) to yours. Set an optional column to
    ``""`` when your table does not have it.
    """

    layout: str = "results"  # "results" or "flags"
    table: str = "fdd.rule_result"
    columns: dict[str, str] = field(default_factory=dict)
    fault_status: tuple[str, ...] = ("FAULT",)
    pass_status: tuple[str, ...] = ("PASS",)
    site_id: str | None = None
    since: Any = None
    until: Any = None

    def col(self, key: str) -> str | None:
        name = self.columns.get(key, key)
        return ident(name) if name else None

    @classmethod
    def for_flags(cls, table: str = "fault_flags", **kw: Any) -> SourceMap:
        return cls(layout="flags", table=table, **kw)


@dataclass
class HistoryMap:
    """Where SI point history lives. Default: Open-FDD ``fdd.input_sample`` joined to ``fdd.point``.

    With ``point_table=""`` the history table itself must carry ``equipment_id``.
    """

    table: str = "fdd.input_sample"
    point_table: str = "fdd.point"
    columns: dict[str, str] = field(default_factory=dict)

    def col(self, key: str) -> str | None:
        name = self.columns.get(key, key)
        return ident(name) if name else None


def paramstyle(conn: Any) -> str:
    mod = type(conn).__module__.split(".")[0]
    return "%s" if mod in {"psycopg", "psycopg2", "pg8000"} else "?"


def _filters(src: SourceMap, ts_col: str, ph: str) -> tuple[str, list[Any]]:
    where, params = [], []
    site = src.col("site_id") if src.columns.get("site_id", "site_id") else None
    if src.site_id is not None and site:
        where.append(f"{site} = {ph}")
        params.append(src.site_id)
    if src.since is not None:
        where.append(f"{ts_col} >= {ph}")
        params.append(src.since)
    if src.until is not None:
        where.append(f"{ts_col} < {ph}")
        params.append(src.until)
    return (" WHERE " + " AND ".join(where)) if where else "", params


def base_cte(src: SourceMap, ph: str = "?") -> tuple[str, list[Any]]:
    """``base`` CTE: one normalised row per evaluation with ``flag`` 1, 0 or NULL (not assessed)."""
    t = ident(src.table)
    eq, rule = src.col("equipment_id"), src.col("rule_id")
    if src.layout == "results":
        subj = src.col("subject_key")
        t0, t1, st = src.col("window_start"), src.col("window_end"), src.col("status")
        fh, ch = src.col("fault_hours"), src.col("covered_hours")
        if not src.fault_status:
            raise ValueError("fault_status needs at least one status value")
        faults = ", ".join(_quote(s) for s in src.fault_status)
        passes = ", ".join(_quote(s) for s in src.pass_status)
        pass_when = f"WHEN {st} IN ({passes}) THEN 0 " if src.pass_status else ""
        where, params = _filters(src, t1, ph)
        sql = (
            "base AS (SELECT "
            f"{eq} AS equipment_id, {rule} AS rule_id, "
            f"{'COALESCE(' + subj + ', ' + _quote('') + ')' if subj else _quote('')} AS subject, "
            f"{t0} AS t0, {t1} AS t1, "
            f"CASE WHEN {st} IN ({faults}) THEN 1 {pass_when}ELSE NULL END AS flag, "
            f"{fh if fh else _NULL} AS fault_h, {ch if ch else _NULL} AS covered_h, "
            f"{_NULL} AS v, {_NULL} AS thr, {_NULL} AS run "
            f"FROM {t}{where})"
        )
        return sql, params
    if src.layout != "flags":
        raise ValueError("layout must be 'results' or 'flags'")
    ts, fl = src.col("timestamp"), src.col("flag")
    v = src.col("value") if src.columns.get("value", "value") else None
    thr = src.col("threshold") if src.columns.get("threshold", "threshold") else None
    run = src.col("running") if src.columns.get("running", "running") else None
    truthy = ", ".join(_quote(s) for s in FLAG_TRUE_TEXT)
    where, params = _filters(src, ts, ph)
    sql = (
        "base AS (SELECT "
        f"{eq} AS equipment_id, {rule} AS rule_id, {_quote('')} AS subject, {ts} AS t0, {ts} AS t1, "
        f"CASE WHEN {fl} IS NULL THEN NULL WHEN LOWER(CAST({fl} AS VARCHAR)) IN ({truthy}) THEN 1 ELSE 0 END AS flag, "
        f"{_NULL} AS fault_h, {_NULL} AS covered_h, "
        f"{v if v else _NULL} AS v, {thr if thr else _NULL} AS thr, "
        + (f"CASE WHEN {run} IS NULL THEN NULL WHEN LOWER(CAST({run} AS VARCHAR)) IN ({truthy}) THEN 1.0 ELSE 0.0 END"
           if run else _NULL)
        + " AS run "
        f"FROM {t}{where})"
    )
    return sql, params


def totals_sql(src: SourceMap, ph: str = "?") -> tuple[str, list[Any]]:
    """Per (equipment, rule): assessed, flagged and unassessed counts, plus value moments for the spread."""
    base, params = base_cte(src, ph)
    sql = (
        f"WITH {base} "
        "SELECT equipment_id, rule_id, "
        "SUM(CASE WHEN flag IS NOT NULL THEN 1 ELSE 0 END) AS n_assessed, "
        "SUM(CASE WHEN flag = 1 THEN 1 ELSE 0 END) AS n_flagged, "
        "SUM(CASE WHEN flag IS NULL THEN 1 ELSE 0 END) AS n_unassessed, "
        "AVG(1.0 * v) AS v_mean, AVG(1.0 * v * v) AS v_sq_mean "
        "FROM base GROUP BY equipment_id, rule_id"
    )
    return sql, params


def episodes_sql(src: SourceMap, sensitivity_frac: float, ph: str = "?") -> tuple[str, list[Any]]:
    """Gaps-and-islands: consecutive flagged rows per (equipment, rule, subject) become one island.

    ``survive`` counts flagged rows whose exceedance |value - threshold| is above ``sensitivity_frac`` times the
    value's standard deviation (compared squared, so no SQRT is needed)."""
    base, params = base_cte(src, ph)
    k2 = float(sensitivity_frac) ** 2
    sql = (
        f"WITH {base}, "
        "stats AS (SELECT equipment_id, rule_id, AVG(1.0 * v) AS m, AVG(1.0 * v * v) AS m2 FROM base "
        "GROUP BY equipment_id, rule_id), "
        "assessed AS (SELECT * FROM base WHERE flag IS NOT NULL), "
        "seq AS (SELECT a.*, "
        "ROW_NUMBER() OVER (PARTITION BY a.equipment_id, a.rule_id, a.subject ORDER BY a.t0, a.t1) AS rn, "
        "ROW_NUMBER() OVER (PARTITION BY a.equipment_id, a.rule_id, a.subject ORDER BY a.t0, a.t1) "
        "- ROW_NUMBER() OVER (PARTITION BY a.equipment_id, a.rule_id, a.subject, a.flag ORDER BY a.t0, a.t1) AS grp, "
        "CASE WHEN a.v IS NULL OR a.thr IS NULL THEN NULL "
        "WHEN a.v >= a.thr THEN 1.0 * a.v - a.thr ELSE 1.0 * a.thr - a.v END AS exceed "
        "FROM assessed a) "
        "SELECT s.equipment_id, s.rule_id, s.subject, MIN(s.t0) AS start_ts, MAX(s.t1) AS end_ts, "
        "MIN(s.rn) AS rn_min, MAX(s.rn) AS rn_max, COUNT(*) AS n_samples, "
        "SUM(s.fault_h) AS fault_h, SUM(s.covered_h) AS covered_h, "
        "AVG(s.exceed) AS exceed_mean, COUNT(s.exceed) AS n_exceed, "
        f"SUM(CASE WHEN s.exceed IS NOT NULL AND s.exceed * s.exceed > {k2!r} * (st.m2 - st.m * st.m) "
        "THEN 1 ELSE 0 END) AS n_survive, "
        "AVG(1.0 * s.run) AS running_share, COUNT(s.run) AS n_run "
        "FROM seq s JOIN stats st ON st.equipment_id = s.equipment_id AND st.rule_id = s.rule_id "
        "WHERE s.flag = 1 GROUP BY s.equipment_id, s.rule_id, s.subject, s.grp"
    )
    return sql, params


def history_sql(hm: HistoryMap, ph: str = "?", *, by_site: bool = False) -> str:
    """Points of one equipment between two timestamps: ``ts, point_id, value, kind``.

    With ``by_site=True`` the query takes the site id as its last parameter (needs a mapped ``site_id`` column)."""
    h = ident(hm.table)
    if by_site and not hm.col("site_id"):
        raise ValueError("history has no site_id column to filter on")
    ts, pk, val = hm.col("ts"), hm.col("point_key"), hm.col("value")
    if hm.point_table:
        p = ident(hm.point_table)
        site = hm.col("site_id")
        eq = hm.col("equipment_id")
        kind = hm.col("kind") if hm.columns.get("kind", "kind") else None
        join = f"p.{site} = s.{site} AND p.{pk} = s.{pk}" if site else f"p.{pk} = s.{pk}"
        return (
            f"SELECT s.{ts} AS ts, s.{pk} AS point_id, s.{val} AS value, {('p.' + kind) if kind else 'NULL'} AS kind "
            f"FROM {h} s JOIN {p} p ON {join} "
            f"WHERE p.{eq} = {ph} AND s.{ts} >= {ph} AND s.{ts} <= {ph}"
            + (f" AND s.{site} = {ph}" if by_site else "")
        )
    eq = hm.col("equipment_id")
    return (
        f"SELECT {ts} AS ts, {pk} AS point_id, {val} AS value, NULL AS kind FROM {h} "
        f"WHERE {eq} = {ph} AND {ts} >= {ph} AND {ts} <= {ph}"
        + (f" AND {hm.col('site_id')} = {ph}" if by_site else "")
    )


def fetch(conn: Any, sql: str, params: list[Any] | tuple = ()) -> tuple[list[str], list[tuple]]:
    """Run a query on any DB-API style connection (sqlite3, duckdb, psycopg) and return columns and rows."""
    cur = conn.cursor() if hasattr(conn, "cursor") else conn
    cur.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()
