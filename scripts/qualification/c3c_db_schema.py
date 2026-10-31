"""Apply disposable Postgres schema slices for C3 SQL-QUAL DB benches (harness-only)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TIMESCALE_ONLY_MARKERS = (
    "create_hypertable",
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
)


def _statements(blob: str) -> list[str]:
    out: list[str] = []
    for chunk in blob.split(";"):
        stmt = chunk.strip()
        if stmt:
            out.append(stmt)
    return out


def timescale_only(stmt: str) -> bool:
    lowered = stmt.lower()
    return any(marker.lower() in lowered for marker in TIMESCALE_ONLY_MARKERS)


def apply_schema_files(cur, relative_paths: list[str]) -> None:
    for rel in relative_paths:
        blob = (ROOT / rel).read_text(encoding="utf-8")
        for stmt in _statements(blob):
            if timescale_only(stmt):
                continue
            cur.execute(stmt)


def apply_si_cutover_fixture_schema(cur) -> None:
    apply_schema_files(
        cur,
        [
            "sql/schema/01_bps_core.sql",
            "sql/schema/02_openfdd_dims.sql",
            "sql/schema/08_analytics_result_cache.sql",
            "sql/schema/10_incremental_fdd.sql",
            "sql/schema/11_point_map_binding_metadata.sql",
            "sql/schema/09_data_revision.sql",
            "sql/schema/12_si_cutover.sql",
        ],
    )
