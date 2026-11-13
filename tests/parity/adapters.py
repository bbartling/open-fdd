"""In-repo engine adapters (implement open_fdd.parity.EngineAdapter).

``NodeEngineAdapter("pglite" | "sqlite")`` runs the SQL pack through ``sql_run.mjs`` (nf-app engines: PGlite = real
Postgres, sql.js = translated SQLite) on a Python-generated dataset.

``DuckDBAdapter`` runs the rendered PostgreSQL pack in DuckDB (UTC, narrowly scoped ``fdd.*`` scalar macros).

``PostgresAdapter`` runs the same pack and canonical ``sql/fdd/postgres/postgres_helpers.sql`` on a standalone plain
PostgreSQL server without Timescale (``POSTGRES_TEST_URL`` + ``OPENFDD_PG_TEST_DISPOSABLE=1``; creates and drops its own
disposable database).

``TimescaleAdapter`` runs the same pack on a real TimescaleDB through the core tables (fdd.point, fdd.input_sample,
fdd.rule_result): it needs a server (``PGURL`` = admin connection, ``OPENFDD_TS_TEST_DISPOSABLE=1``; the runner creates
and drops its own database) and is skipped by the tests when none is configured. ``ingest="si"`` (default) loads the
exact same SI fixture as the other engines; ``ingest="native"`` exercises native-unit ingestion conversion.
"""
from __future__ import annotations

import copy
import json
import math
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PACK_PG_PATH = ROOT / "nf-app" / "rules" / "pack-postgres.json"
PG_HELPERS_PATH = ROOT / "sql" / "fdd" / "postgres" / "postgres_helpers.sql"


def node() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("node is required for the SQL side (nf-app engines)")
    return exe


def _sanitize_value(v: Any) -> Any:
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _sanitize_rows(columns: Sequence[str], rows: Sequence[tuple]) -> list[dict]:
    out = []
    for row in rows:
        rec = {}
        for col, val in zip(columns, row):
            rec[col] = _sanitize_value(val)
        out.append(rec)
    return out


def _table_columns(pack: dict, dataset) -> dict[str, list[dict]]:
    out = {t: [dict(c) for c in cols] for t, cols in pack["contract"].items()}
    have = {c["name"] for c in out["history"]}
    for c in dataset.history_columns:
        if c["name"] not in have:
            out["history"].append({"name": c["name"], "type": "text" if c["type"] == "text" else "double"})
            have.add(c["name"])
    return out


def _cell_value(row: dict, col: dict) -> Any:
    key = "ts" if col["name"] == "timestamp_utc" else col["name"]
    raw = row.get(key)
    if raw is None:
        return None
    if col["type"] == "timestamp":
        return datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
    if col["type"] == "text":
        return str(raw)
    val = float(raw)
    return None if math.isnan(val) else val


def _peak_rss_mb() -> float:
    if os.name == "nt":
        return 0.0
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1048576.0 if sys.platform == "darwin" else 1024.0), 1)


import sys  # noqa: E402


class NodeEngineAdapter:
    """load(dataset) writes the loader JSON; run(rule_ids) spawns ``sql_run.mjs`` for this engine only."""

    def __init__(self, kind: str):
        if kind not in ("pglite", "sqlite"):
            raise ValueError(kind)
        self.kind = kind
        self.name = kind
        self._dir: Path | None = None
        self._ds_file: Path | None = None
        self.stats: dict = {}
        self.raw: dict = {}

    def load(self, dataset) -> None:
        self.close()
        self._dir = Path(tempfile.mkdtemp(prefix=f"parity_{self.kind}_"))
        self._ds_file = self._dir / "dataset.json"
        self._ds_file.write_text(json.dumps(dataset.to_loader_json(), ensure_ascii=False), encoding="utf-8")

    def run(self, rule_ids: Sequence[str] | None = None, rule_sql: dict | None = None) -> dict[str, list[dict]]:
        if self._ds_file is None:
            raise RuntimeError("load(dataset) before run()")
        out = self._dir / "out.json"
        cmd = [node(), str(HERE / "sql_run.mjs"), "--dataset", str(self._ds_file), "--out", str(out), "--engines", self.kind]
        if rule_ids:
            cmd += ["--rules", ",".join(rule_ids)]
        if rule_sql:
            f = self._dir / "rule_sql.json"
            f.write_text(json.dumps(rule_sql), encoding="utf-8")
            cmd += ["--rule-sql", str(f)]
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"sql_run.mjs failed:\n{proc.stdout}\n{proc.stderr}")
        self.raw = json.loads(out.read_text(encoding="utf-8"))
        self.stats = {"wall_s": time.time() - t0, "timing": self.raw["timing"], "memory": self.raw["memory"],
                      "errors": self.raw["errors"]}
        return self.raw["results"][self.kind]

    def close(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = self._ds_file = None


DUCKDB_HELPERS_SQL = """
CREATE SCHEMA IF NOT EXISTS fdd;

CREATE OR REPLACE MACRO fdd.try_double(v) AS (
  CASE
    WHEN ISFINITE(TRY_CAST(NULLIF(TRIM(CAST(v AS VARCHAR)), '') AS DOUBLE))
      THEN TRY_CAST(NULLIF(TRIM(CAST(v AS VARCHAR)), '') AS DOUBLE)
    ELSE NULL
  END
);

CREATE OR REPLACE MACRO fdd.norm_unit(v) AS (
  LOWER(REGEXP_REPLACE(COALESCE(TRIM(CAST(v AS VARCHAR)), ''), '[^a-zA-Z0-9]', '', 'g'))
);

CREATE OR REPLACE MACRO fdd.quantity_for_sql_role(role) AS (
  CASE
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('ahu_sat', 'chw_return_t', 'chw_supply_sp', 'chw_supply_t',
      'cooling_coil_entering_temp', 'cooling_coil_leaving_temp', 'cooling_sp', 'cw_return_t',
      'cw_supply_t', 'heating_coil_entering_temp', 'heating_coil_leaving_temp', 'heating_sp',
      'hw_return_t', 'hw_supply_t', 'mat', 'oa_t', 'preheat_leave_t', 'rat', 'sat', 'sat_sp',
      'vav_discharge_t', 'vav_inlet_t', 'web_oa_dp', 'web_oa_t', 'web_wb_t', 'zone_air_temp_sp', 'zone_t')
      THEN 'absolute_temperature'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('ma_h', 'oa_h', 'ra_h', 'sa_h', 'web_oa_h', 'zone_rh')
      THEN 'relative_humidity'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chw_dp', 'chw_dp_sp', 'duct_static', 'duct_static_sp') THEN 'air_pressure'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chw_flow', 'min_flow_sp', 'vav_total_flow', 'zone_airflow_sp', 'zone_flow') THEN 'volume_flow'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chiller_power', 'electric_kw') THEN 'power'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('electric_kwh', 'kwh') THEN 'energy'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chiller_amps', 'chiller_current') THEN 'electric_current'
    WHEN TRIM(CAST(role AS VARCHAR)) = 'zone_co2' THEN 'concentration'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chw_reset_request_sum', 'hw_reset_request_sum', 'static_reset_request') THEN 'count'
    ELSE NULL
  END
);

CREATE OR REPLACE MACRO fdd.unit_declares_quantity(unit, quantity) AS (
  CASE
    WHEN unit IS NULL OR TRIM(CAST(unit AS VARCHAR)) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN fdd.norm_unit(unit) IN ('c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN (
      fdd.norm_unit(unit) IN ('pct', 'percent', 'rh', 'percentrelativehumidity')
      OR STRPOS(CAST(unit AS VARCHAR), '%') > 0
    )
    WHEN quantity = 'air_pressure' THEN fdd.norm_unit(unit) IN ('pa', 'pascal')
    WHEN quantity = 'volume_flow' THEN fdd.norm_unit(unit) = 'ls'
    WHEN quantity = 'power' THEN fdd.norm_unit(unit) = 'kw'
    WHEN quantity = 'energy' THEN fdd.norm_unit(unit) = 'kwh'
    WHEN quantity = 'electric_current' THEN fdd.norm_unit(unit) = 'a'
    WHEN quantity = 'concentration' THEN fdd.norm_unit(unit) = 'ppm'
    WHEN quantity = 'count' THEN fdd.norm_unit(unit) = 'count'
    ELSE false
  END
);

CREATE OR REPLACE MACRO fdd.is_expected_constant_sql_role(role) AS (
  CASE
    WHEN role IS NULL OR TRIM(CAST(role AS VARCHAR)) = '' THEN false
    WHEN fdd.norm_unit(role) LIKE '%sp' THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'setpoint') > 0 THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'status') > 0 THEN true
    WHEN fdd.norm_unit(role) LIKE '%cmd' THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'command') > 0 THEN true
    WHEN fdd.norm_unit(role) = 'occmode' THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'occupied') > 0 THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'occupancy') > 0 THEN true
    WHEN fdd.norm_unit(role) = 'loopenabled' THEN true
    ELSE false
  END
);

CREATE OR REPLACE MACRO fdd.sweep_assessable_sql_role(role, unit) AS (
  CASE
    WHEN fdd.is_expected_constant_sql_role(role) THEN false
    ELSE fdd.unit_declares_quantity(unit, fdd.quantity_for_sql_role(role))
  END
);

CREATE OR REPLACE MACRO fdd.mask_sweep_val(role, unit, val) AS (
  CASE WHEN fdd.sweep_assessable_sql_role(role, unit) THEN CAST(val AS DOUBLE) ELSE NULL END
);

CREATE OR REPLACE MACRO to_char(ts, fmt) AS (
  CASE
    WHEN fmt = 'YYYY-MM' THEN strftime(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC', '%Y-%m')
    WHEN fmt = 'YYYY-MM-DD' THEN strftime(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC', '%Y-%m-%d')
    ELSE strftime(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC', fmt)
  END
);
"""


class DuckDBAdapter:
    """Runs the rendered PostgreSQL rule pack in DuckDB with UTC and narrowly scoped ``fdd.*`` macros."""

    name = "duckdb"

    def __init__(self):
        self._conn = None
        self._pack: dict | None = None
        self.stats: dict = {}
        self.raw: dict = {}
        self._load_ms: int = 0

    def load(self, dataset) -> None:
        import duckdb

        self.close()
        self._pack = json.loads(PACK_PG_PATH.read_text(encoding="utf-8"))
        self._conn = duckdb.connect(":memory:")
        self._conn.execute("SET TimeZone = 'UTC'")
        self._conn.execute(DUCKDB_HELPERS_SQL)

        t0 = time.time()
        cols = _table_columns(self._pack, dataset)
        input_map = {
            "history": dataset.history,
            "weather": dataset.weather,
            "sensor_history": dataset.sensor_history,
            "utility_interval": dataset.utility_interval,
            "utility_monthly": dataset.utility_monthly,
        }
        duck_type = {"double": "DOUBLE", "text": "VARCHAR", "timestamp": "TIMESTAMPTZ"}
        for table, spec in cols.items():
            ddl = ", ".join(f'"{c["name"]}" {duck_type[c["type"]]}' for c in spec)
            self._conn.execute(f"DROP TABLE IF EXISTS {table}")
            self._conn.execute(f"CREATE TABLE {table} ({ddl})")
            rows = input_map.get(table) or []
            if rows:
                placeholders = ", ".join(["?"] * len(spec))
                names = ", ".join(f'"{c["name"]}"' for c in spec)
                tuples = [tuple(_cell_value(row, c) for c in spec) for row in rows]
                self._conn.executemany(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", tuples)
        self._load_ms = int((time.time() - t0) * 1000)

    def run(self, rule_ids: Sequence[str] | None = None, rule_sql: dict | None = None) -> dict[str, list[dict]]:
        if self._conn is None or self._pack is None:
            raise RuntimeError("load(dataset) before run()")
        target_ids = list(rule_ids) if rule_ids else list(self._pack["rules"].keys())
        results: dict[str, list[dict]] = {}
        errors: dict[str, str] = {}
        t0 = time.time()
        for rid in target_ids:
            sql = (rule_sql or {}).get(rid) or self._pack["rules"][rid]["sql"]
            try:
                cur = self._conn.execute(sql)
                cols = [d[0] for d in cur.description]
                results[rid] = _sanitize_rows(cols, cur.fetchall())
            except Exception as exc:
                errors[f"duckdb {rid}"] = str(exc)
                results[rid] = []
        rules_ms = int((time.time() - t0) * 1000)
        self.raw = {
            "results": {"duckdb": results},
            "errors": errors,
            "timing": {"duckdb_load_ms": self._load_ms, "duckdb_rules_ms": rules_ms},
            "memory": {"duckdb_rss_peak_mb": _peak_rss_mb()},
        }
        self.stats = {
            "wall_s": (self._load_ms + rules_ms) / 1000.0,
            "timing": self.raw["timing"],
            "memory": self.raw["memory"],
            "errors": errors,
        }
        return results

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def postgres_configured() -> bool:
    """True when a standalone disposable PostgreSQL server is configured (distinct from Timescale's PGURL)."""
    return bool(os.environ.get("POSTGRES_TEST_URL")) and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"


def _url_for_db(base_url: str, dbname: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse(parsed._replace(path=f"/{dbname}"))


class PostgresAdapter:
    """Runs the rendered PostgreSQL rule pack and ``postgres_helpers.sql`` on standalone PostgreSQL (no Timescale)."""

    name = "postgres"

    def __init__(self):
        self._dataset = None
        self._pack: dict | None = None
        self.stats: dict = {}
        self.raw: dict = {}

    def load(self, dataset) -> None:
        if not postgres_configured():
            raise RuntimeError("PostgresAdapter needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
        self._dataset = dataset
        self._pack = json.loads(PACK_PG_PATH.read_text(encoding="utf-8"))

    def run(self, rule_ids: Sequence[str] | None = None, rule_sql: dict | None = None) -> dict[str, list[dict]]:
        if self._dataset is None or self._pack is None:
            raise RuntimeError("load(dataset) before run()")
        import psycopg

        base_url = os.environ["POSTGRES_TEST_URL"]
        token = secrets.token_hex(6)
        dbname = f"openfdd_pg_parity_{token}"
        target_ids = list(rule_ids) if rule_ids else list(self._pack["rules"].keys())

        results: dict[str, list[dict]] = {}
        errors: dict[str, str] = {}
        timing: dict[str, int] = {}
        t_wall = time.time()

        with psycopg.connect(base_url, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{dbname}"')
        try:
            with psycopg.connect(_url_for_db(base_url, dbname), autocommit=True) as conn:
                conn.execute("SET TIME ZONE 'UTC'")
                conn.execute(
                    "CREATE TABLE _openfdd_disposable (token text PRIMARY KEY, created_at timestamptz DEFAULT now())"
                )
                conn.execute("INSERT INTO _openfdd_disposable (token) VALUES (%s)", (token,))
                conn.execute(PG_HELPERS_PATH.read_text(encoding="utf-8"))

                t0 = time.time()
                cols = _table_columns(self._pack, self._dataset)
                input_map = {
                    "history": self._dataset.history,
                    "weather": self._dataset.weather,
                    "sensor_history": self._dataset.sensor_history,
                    "utility_interval": self._dataset.utility_interval,
                    "utility_monthly": self._dataset.utility_monthly,
                }
                pg_type = {"double": "DOUBLE PRECISION", "text": "VARCHAR", "timestamp": "TIMESTAMPTZ"}
                for table, spec in cols.items():
                    ddl = ", ".join(f'"{c["name"]}" {pg_type[c["type"]]}' for c in spec)
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                    conn.execute(f"CREATE TABLE {table} ({ddl})")
                    rows = input_map.get(table) or []
                    if rows:
                        names = ", ".join(f'"{c["name"]}"' for c in spec)
                        placeholders = ", ".join(["%s"] * len(spec))
                        with conn.cursor() as cur:
                            cur.executemany(
                                f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                                [tuple(_cell_value(row, c) for c in spec) for row in rows],
                            )
                conn.execute("CREATE INDEX IF NOT EXISTS history_eq_ts ON history(equipment_id, timestamp_utc)")
                conn.execute("ANALYZE history")
                timing["postgres_load_ms"] = int((time.time() - t0) * 1000)

                t1 = time.time()
                for rid in target_ids:
                    sql = (rule_sql or {}).get(rid) or self._pack["rules"][rid]["sql"]
                    try:
                        with conn.cursor() as cur:
                            cur.execute(sql)
                            col_names = [d[0] for d in cur.description]
                            results[rid] = _sanitize_rows(col_names, cur.fetchall())
                    except Exception as exc:
                        errors[f"postgres {rid}"] = str(exc)
                        results[rid] = []
                timing["postgres_rules_ms"] = int((time.time() - t1) * 1000)
        finally:
            with psycopg.connect(base_url, autocommit=True) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (dbname,),
                )
                admin.execute(f'DROP DATABASE IF EXISTS "{dbname}"')

        self.raw = {
            "results": {"postgres": results},
            "errors": errors,
            "timing": timing,
            "memory": {"postgres_rss_peak_mb": _peak_rss_mb()},
        }
        self.stats = {
            "wall_s": round(time.time() - t_wall, 3),
            "timing": timing,
            "memory": self.raw["memory"],
            "errors": errors,
        }
        return results

    def close(self) -> None:
        self._dataset = None


def timescale_configured() -> bool:
    """True when a disposable TimescaleDB is configured for the tests (never inferred from anything else)."""
    return bool(os.environ.get("PGURL")) and os.environ.get("OPENFDD_TS_TEST_DISPOSABLE") == "1"


class TimescaleAdapter:
    """load(dataset) writes the core rows; run() spawns ``nf-app/timescale/test/parity_run.mjs``.

    ``ingest="si"`` (default) loads the exact same SI fixture as PGlite/SQLite/DuckDB/Postgres.
    ``ingest="native"`` seeds ``public.data`` from ``to_imperial(ds).to_core_rows()`` to test the affine conversion view.
    """

    name = "timescale"

    def __init__(self, plan_only: bool = False, ingest: str = "si"):
        if ingest not in ("si", "native"):
            raise ValueError(ingest)
        self.plan_only = plan_only
        self.ingest = ingest
        self._dir: Path | None = None
        self._in: Path | None = None
        self.stats: dict = {}
        self.raw: dict = {}

    def load(self, dataset) -> None:
        from open_fdd.parity import to_imperial

        self.close()
        if not self.plan_only and not timescale_configured():
            raise RuntimeError("TimescaleAdapter needs PGURL and OPENFDD_TS_TEST_DISPOSABLE=1 (a disposable TimescaleDB)")
        self._dir = Path(tempfile.mkdtemp(prefix="parity_timescale_"))
        self._in = self._dir / "input.json"
        site = "parity"
        src_ds = to_imperial(dataset) if self.ingest == "native" else dataset
        points, samples = src_ds.to_core_rows(site)
        columnar: dict[str, list[list]] = {}
        for _site, key, ts, value in samples:
            cols = columnar.setdefault(key, [[], []])
            cols[0].append(ts)
            cols[1].append(value)
        meta = dataset.meta
        t0, steps = meta["t0_ms"], meta["steps"]
        si_history: dict[str, list[dict]] = {}
        for row in dataset.history:
            si_history.setdefault(row["equipment_id"], []).append(row)
        self._in.write_text(json.dumps({
            "site_id": site, "ingest": self.ingest, "step_seconds": dataset.step_seconds,
            "window": {"from_ms": t0, "to_ms": t0 + steps * dataset.step_seconds * 1000},
            "points": points, "samples": columnar, "si_history": si_history, "weather": dataset.weather,
            "utility_interval": dataset.utility_interval, "utility_monthly": dataset.utility_monthly,
            "history_columns": dataset.history_columns}, ensure_ascii=False), encoding="utf-8")

    def loaded_dataset(self, dataset):
        loaded = self.raw.get("loaded_history") or {}
        out = copy.deepcopy(dataset)
        out.__dict__.pop("sensor_history", None)
        cells = {(e, r["ts"]): r for e, rows in loaded.items() for r in rows}
        for row in out.history:
            got = cells.get((row["equipment_id"], row["ts"]))
            if got:
                row.update({k: v for k, v in got.items() if k != "ts"})
        return out

    def run(self, rule_ids: Sequence[str] | None = None) -> dict[str, list[dict]]:
        if self._in is None:
            raise RuntimeError("load(dataset) before run()")
        out = self._dir / "out.json"
        cmd = [node(), str(ROOT / "nf-app/timescale/test/parity_run.mjs"), "--in", str(self._in), "--out", str(out)]
        if self.plan_only:
            cmd.append("--plan-only")
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError("parity_run.mjs failed: " + proc.stdout + " " + proc.stderr)
        self.raw = json.loads(out.read_text(encoding="utf-8"))
        self.stats = {"wall_s": time.time() - t0, "timing": self.raw.get("timing", {}), "memory": self.raw.get("memory", {}),
                      "errors": self.raw.get("errors", {})}
        results = self.raw.get("results", {})
        return {r: results.get(r, []) for r in rule_ids} if rule_ids else results

    def close(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = self._in = None


ADAPTERS = {
    "pglite": lambda: NodeEngineAdapter("pglite"),
    "sqlite": lambda: NodeEngineAdapter("sqlite"),
    "duckdb": lambda: DuckDBAdapter(),
    "postgres": lambda: PostgresAdapter(),
    "timescale": lambda: TimescaleAdapter(ingest="si"),
}
