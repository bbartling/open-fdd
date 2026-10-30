"""W4f analytics P2 — pandas SI vs Timescale SQL on CI SI seeds (#1284).

Every file under ``sql/analytics/postgres/queries/`` is compared to a pandas SI
oracle (numeric columns within tolerance, row keys equal; keys-only when no numerics).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
QUERIES_DIR = REPO / "sql" / "analytics" / "postgres" / "queries"
REGISTRY_PATH = REPO / "sql" / "analytics" / "registry.json"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_fdd.analytics.si_thresholds import ECON_DIAG_DT_MIN_C  # noqa: E402

from scripts.stress.si_cutover import ci_timescale_sql as cts  # noqa: E402




def all_analytics_sql_stems() -> tuple[str, ...]:
    paths = sorted(QUERIES_DIR.glob("*.sql"))
    stems = tuple(p.stem for p in paths)
    if len(stems) != 19:
        raise RuntimeError(f"expected 19 analytics SQL bodies, found {len(stems)}")
    return stems


def registry_sql_paths() -> set[str]:
    doc = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    out: set[str] = set()
    for row in doc.get("queries") or []:
        path = str(row.get("sql_path") or "")
        if path:
            out.add(path)
    # sql-anomaly uses two files; registry lists zscore only.
    out.add("sql/analytics/postgres/queries/sql_anomaly_series.sql")
    return out


def _simplify_equipment_scope_sql(sql: str) -> str:
    """Drop polymorphic NULL/empty equipment binds — CI seeds always pass a text[]."""
    out = re.sub(
        r"\(\s*\$4::text\[\]\s*IS NULL\s*OR cardinality\(\$4\)\s*=\s*0\s*OR\s+"
        r"((?:[\w.]+\.)?equipment_id)\s*=\s*ANY\s*\(\s*\$4\s*\)\s*\)",
        r"\1 = ANY ($4)",
        sql,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\(\s*\$2::text\[\]\s*IS NULL\s*OR cardinality\(\$2\)\s*=\s*0\s*OR\s+"
        r"equipment_id\s*=\s*ANY\s*\(\s*\$2\s*\)\s*\)",
        "equipment_id = ANY ($2)",
        out,
        flags=re.IGNORECASE,
    )


def _dollar_sql_to_psycopg(sql: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    """Render postgres ``$n`` placeholders for psycopg (``%s`` only)."""
    mark = "\x00OFDD_PG_BIND\x00"
    code_lines: list[str] = []
    for line in sql.splitlines():
        dash = line.find("--")
        code_lines.append(line[:dash] if dash >= 0 else line)
    code = "\n".join(code_lines)
    indices = [int(m.group(1)) for m in re.finditer(r"\$(\d+)", code)]
    if not indices:
        return sql, ()
    need = max(indices)
    if len(params) != need:
        raise ValueError(f"analytics SQL expects {need} bind(s), got {len(params)}")
    expanded: list[Any] = []

    def _sub(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        expanded.append(params[idx - 1])
        return mark

    out_lines: list[str] = []
    for line in sql.splitlines():
        dash = line.find("--")
        if dash >= 0:
            code_part, comment_part = line[:dash], line[dash:]
        else:
            code_part, comment_part = line, ""
        code_part = re.sub(r"\$(\d+)(?!\d)", _sub, code_part)
        code_part = code_part.replace("%", "%%")
        code_part = code_part.replace(mark, "%s")
        out_lines.append(code_part + comment_part)
    return "\n".join(out_lines), tuple(expanded)


def _statements(text: str) -> list[str]:
    current: list[str] = []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";").strip()
            current = []
            if stmt:
                out.append(stmt)
    tail = "\n".join(current).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def _window_from_frame(frame) -> tuple[str | None, str | None]:
    if frame is None or len(frame.index) == 0:
        return None, None
    start = frame.index[0].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    end = frame.index[-1].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    return start, end


def _seed_si_site(
    conn,
    *,
    building_id: str,
    equipment_id: str,
    equip_type: str,
    si_frame,
) -> None:
    parity = cts._load_parity_module()
    parity.apply_schema(conn)
    sql_cols = cts.frame_sql_columns(si_frame)
    with conn.cursor() as cur:
        cts.purge_site(cur, building_id)
        cts.seed_frame(
            cur,
            parity,
            site_id=building_id,
            equipment_id=equipment_id,
            equip_type=equip_type,
            frame=si_frame,
            si_storage=True,
        )
        cts.fill_history(cur, building_id, sql_cols)
    conn.commit()


def analytics_bind_tuple(
    stem: str,
    *,
    site_id: str,
    window_start: str | None,
    window_end: str | None,
    equipment_id: str,
    equipment_ids: list[str] | None = None,
    cur=None,
) -> tuple[Any, ...]:
    eq = equipment_ids if equipment_ids is not None else [equipment_id]
    if stem == "plant_health_inventory":
        return (site_id, eq)
    base: tuple[Any, ...] = (site_id, window_start, window_end, eq)
    if stem == "economizer_deltas":
        return base + (ECON_DIAG_DT_MIN_C,)
    if stem == "role_timeseries":
        return base + ("fan_status", 500)
    if stem == "bas_vs_web_oat":
        oa_key = f"{equipment_id}.oa_t"
        if cur is not None:
            cur.execute(
                """
                SELECT openfdd_key FROM authorized_series
                WHERE site_id = %s AND equipment_id = %s AND role = 'oa_t'
                ORDER BY openfdd_key LIMIT 1
                """,
                (site_id, equipment_id),
            )
            row = cur.fetchone()
            if row and row[0]:
                oa_key = str(row[0])
        return base + (oa_key, 7200.0, 500)
    if stem == "sql_anomaly_zscore":
        return base + (20, 3.0, False)
    return base


def _typed_bind(value: Any) -> Any:
    """Send window bounds as timestamptz (not untyped text) so expressions such as
    ``$2 - make_interval(...)`` resolve exactly as with the typed Rust binds."""
    if isinstance(value, str) and len(value) == 20 and value.endswith("Z") and value[10] == "T":
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _exec_analytics_sql(
    cur,
    stem: str,
    *,
    site_id: str,
    window_start: str | None,
    window_end: str | None,
    equipment_ids: list[str] | None,
    extra_binds: tuple[Any, ...] = (),
) -> list[tuple[Any, ...]]:
    del extra_binds
    sql_path = QUERIES_DIR / f"{stem}.sql"
    sql = _simplify_equipment_scope_sql(sql_path.read_text(encoding="utf-8"))
    eid = equipment_ids[0] if equipment_ids else site_id
    eq_arr = equipment_ids if equipment_ids else None
    binds = analytics_bind_tuple(
        stem,
        site_id=site_id,
        window_start=window_start,
        window_end=window_end,
        equipment_id=eid,
        equipment_ids=eq_arr,
        cur=cur,
    )
    binds = tuple(_typed_bind(b) for b in binds)
    sql_pg, binds_pg = _dollar_sql_to_psycopg(sql, binds)
    cur.execute(sql_pg, binds_pg)
    return cur.fetchall()


















