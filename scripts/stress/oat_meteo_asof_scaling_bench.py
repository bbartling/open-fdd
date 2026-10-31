#!/usr/bin/env python3
"""Measure OAT-METEO rule SQL scaling on disposable Postgres (#1439).

Runs EXPLAIN (ANALYZE, BUFFERS) and wall-clock timings at configurable
history row counts per equipment. Reports a log-log growth exponent from warm
timings and the margin to OPENFDD_FDD_RUN_TIMEOUT_SECS (default 900).

Does not mutate product data. Intended for stress evidence and local diagnosis:

  OPENFDD_DATABASE_URL=postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd \\
    python3 scripts/stress/oat_meteo_asof_scaling_bench.py --json-out /tmp/oat-scaling.json

  python3 scripts/stress/oat_meteo_asof_scaling_bench.py --quick
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULE_SQL = ROOT / "sql/fdd/postgres/rules/oat_meteo_fault.sql"
DEFAULT_SIZES = (700, 4700, 35000, 50000)
QUICK_SIZES = (700, 4700)


def _render_rule(*, web_asof_bound_seconds: float) -> str:
    text = RULE_SQL.read_text(encoding="utf-8")
    repl = {
        "{{WEB_ASOF_BOUND_SECONDS}}": str(web_asof_bound_seconds),
        "{{OAT_ERR}}": "2.777778",
        "{{CONFIRM_SECONDS}}": "900",
        "{{MAX_GAP_HOURS}}": "1.0",
    }
    for key, val in repl.items():
        text = text.replace(key, val)
    return text


def _connect(url: str):
    try:
        import psycopg2
    except ImportError as exc:  # pragma: no cover - env specific
        raise SystemExit(
            "psycopg2 required: pip install psycopg2-binary or use system python3-psycopg2"
        ) from exc
    return psycopg2.connect(url)


def _setup_fixture(cur, *, rows_per_equipment: int, equipment_count: int, web_mode: str) -> None:
    cur.execute(
        """
        DROP TABLE IF EXISTS history, weather CASCADE;
        CREATE UNLOGGED TABLE history (
          equipment_id text,
          timestamp_utc timestamptz,
          oa_t double precision,
          web_oa_t double precision
        );
        CREATE UNLOGGED TABLE weather (
          timestamp_utc timestamptz,
          web_oa_t double precision
        );
        CREATE INDEX oat_bench_hist_ts ON history (timestamp_utc);
        CREATE INDEX oat_bench_weather_ts ON weather (timestamp_utc);
        """
    )
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    eqs = [f"AHU_{i}" for i in range(equipment_count)]
    hist: list[tuple[str, str, float, None]] = []
    for i in range(rows_per_equipment):
        ts = (t0 + timedelta(minutes=5 * i)).isoformat()
        for eq in eqs:
            hist.append((eq, ts, 10.0 + (i % 7) * 0.1, None))
    import psycopg2.extras

    psycopg2.extras.execute_values(
        cur, "INSERT INTO history VALUES %s", hist, page_size=5000
    )
    n_web = max(50, rows_per_equipment // 20)
    web_rows: list[tuple[str, float]] = []
    if web_mode == "sparse":
        for j in range(n_web):
            ts = (t0 + timedelta(hours=6 * j)).isoformat()
            web_rows.append((ts, 9.5))
    elif web_mode == "duplicate":
        for j in range(n_web):
            ts = (t0 + timedelta(minutes=20 * (j // 3))).isoformat()
            web_rows.append((ts, 9.5 + (j % 3) * 0.01))
    else:
        step = max(1, rows_per_equipment // max(1, n_web))
        for j in range(n_web):
            ts = (t0 + timedelta(minutes=5 * j * step)).isoformat()
            web_rows.append((ts, 9.5))
    psycopg2.extras.execute_values(
        cur, "INSERT INTO weather VALUES %s", web_rows, page_size=5000
    )
    cur.execute("ANALYZE history; ANALYZE weather;")


def _time_rule(cur, sql: str) -> tuple[float, float, int]:
    cur.execute("DISCARD ALL")
    t0 = time.perf_counter()
    cur.execute(sql)
    cur.fetchall()
    warm_s = time.perf_counter() - t0
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}")
    plan = "\n".join(row[0] for row in cur.fetchall())
    exec_ms = 0.0
    for line in plan.splitlines():
        if "Execution Time:" in line:
            exec_ms = float(line.split("Execution Time:")[1].split(" ms")[0].strip())
            break
    subplans = plan.count("SubPlan")
    return warm_s, exec_ms, subplans


def _growth_exponent(rows: list[int], warm_seconds: list[float]) -> float:
    if len(rows) < 2:
        return float("nan")
    log_n = [math.log(float(n)) for n in rows]
    log_t = [math.log(max(t, 1e-9)) for t in warm_seconds]
    mean_ln = sum(log_n) / len(log_n)
    mean_lt = sum(log_t) / len(log_t)
    num = sum((log_n[i] - mean_ln) * (log_t[i] - mean_lt) for i in range(len(rows)))
    den = sum((log_n[i] - mean_ln) ** 2 for i in range(len(rows)))
    if den == 0.0:
        return float("nan")
    return num / den


def run_benchmark(
    *,
    database_url: str,
    sizes: tuple[int, ...],
    equipment_count: int,
    web_mode: str,
    web_asof_bound_seconds: float,
    fdd_timeout_secs: float,
) -> dict:
    sql = _render_rule(web_asof_bound_seconds=web_asof_bound_seconds)
    conn = _connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()
    rows_out: list[dict] = []
    warm_times: list[float] = []
    size_list: list[int] = []
    for n in sizes:
        _setup_fixture(cur, rows_per_equipment=n, equipment_count=equipment_count, web_mode=web_mode)
        cold_s, cold_ms, _ = _time_rule(cur, sql)
        warm_s, warm_ms, subplans = _time_rule(cur, sql)
        warm_times.append(warm_s)
        size_list.append(n)
        rows_out.append(
            {
                "rows_per_equipment": n,
                "equipment_count": equipment_count,
                "total_history_rows": n * equipment_count,
                "web_mode": web_mode,
                "cold_wall_seconds": round(cold_s, 4),
                "warm_wall_seconds": round(warm_s, 4),
                "explain_execution_ms": round(warm_ms, 2),
                "explain_subplan_count": subplans,
                "cold_explain_execution_ms": round(cold_ms, 2),
            }
        )
    exponent = _growth_exponent(size_list, warm_times)
    largest = rows_out[-1] if rows_out else {}
    warm_largest = float(largest.get("warm_wall_seconds") or 0.0)
    margin = fdd_timeout_secs - warm_largest
    conn.close()
    return {
        "rule_sql_path": str(RULE_SQL.relative_to(ROOT)),
        "web_asof_bound_seconds": web_asof_bound_seconds,
        "fdd_run_timeout_seconds": fdd_timeout_secs,
        "warm_log_log_exponent": None if math.isnan(exponent) else round(exponent, 4),
        "superlinear_growth": bool(not math.isnan(exponent) and exponent > 1.1),
        "timeout_margin_seconds_largest_case": round(margin, 2),
        "cases": rows_out,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        or os.environ.get("OPENFDD_TEST_DATABASE_URL", "").strip(),
        help="Disposable Postgres URL (OPENFDD_DATABASE_URL or OPENFDD_TEST_DATABASE_URL)",
    )
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help="Comma-separated rows per equipment (default: 700,4700,35000,50000)",
    )
    parser.add_argument("--equipment-count", type=int, default=1)
    parser.add_argument(
        "--web-mode",
        choices=("dense", "sparse", "duplicate"),
        default="dense",
    )
    parser.add_argument("--web-asof-bound-seconds", type=float, default=1500.0)
    parser.add_argument(
        "--fdd-timeout-seconds",
        type=float,
        default=float(os.environ.get("OPENFDD_FDD_RUN_TIMEOUT_SECS", "900")),
    )
    parser.add_argument("--json-out", default="", help="Write JSON evidence path")
    parser.add_argument(
        "--quick",
        action="store_true",
        help=f"Use smaller sizes {QUICK_SIZES} for CI smoke",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        print("FAIL: set OPENFDD_DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2
    sizes = QUICK_SIZES if args.quick else tuple(int(s.strip()) for s in args.sizes.split(",") if s.strip())
    report = run_benchmark(
        database_url=args.database_url,
        sizes=sizes,
        equipment_count=args.equipment_count,
        web_mode=args.web_mode,
        web_asof_bound_seconds=args.web_asof_bound_seconds,
        fdd_timeout_secs=args.fdd_timeout_seconds,
    )
    print(json.dumps(report, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["superlinear_growth"]:
        print(
            f"NOTE: warm exponent {report['warm_log_log_exponent']} > 1.1 (superlinear)",
            file=sys.stderr,
        )
    if report["timeout_margin_seconds_largest_case"] < 0:
        print("WARN: largest warm timing exceeds OPENFDD_FDD_RUN_TIMEOUT_SECS", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
