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


def _explain_plan(cur, sql: str) -> tuple[str, float, int]:
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}")
    plan = "\n".join(row[0] for row in cur.fetchall())
    exec_ms = 0.0
    for line in plan.splitlines():
        if "Execution Time:" in line:
            exec_ms = float(line.split("Execution Time:")[1].split(" ms")[0].strip())
            break
    subplans = plan.count("SubPlan")
    return plan, exec_ms, subplans


def _time_rule(cur, sql: str) -> tuple[float, float, int]:
    cur.execute("DISCARD ALL")
    t0 = time.perf_counter()
    cur.execute(sql)
    cur.fetchall()
    warm_s = time.perf_counter() - t0
    _, exec_ms, subplans = _explain_plan(cur, sql)
    return warm_s, exec_ms, subplans


def _time_rule_repeated(cur, sql: str, *, repeats: int) -> dict[str, float]:
    """Cold once, then warm repeats for median/p95 wall times."""
    cold_s, cold_ms, _ = _time_rule(cur, sql)
    warm: list[float] = []
    for _ in range(max(1, repeats - 1)):
        warm_s, _, _ = _time_rule(cur, sql)
        warm.append(warm_s)
    warm_sorted = sorted(warm) if warm else [cold_s]
    mid = len(warm_sorted) // 2
    median = warm_sorted[mid] if len(warm_sorted) % 2 else (
        (warm_sorted[mid - 1] + warm_sorted[mid]) / 2.0
    )
    p95_idx = max(0, int(math.ceil(0.95 * len(warm_sorted))) - 1)
    return {
        "cold_wall_seconds": round(cold_s, 4),
        "cold_explain_execution_ms": round(cold_ms, 2),
        "warm_wall_seconds_median": round(median, 4),
        "warm_wall_seconds_p95": round(warm_sorted[p95_idx], 4),
        "warm_repeats": len(warm_sorted),
    }


def _plan_join_signals(plan: str) -> dict[str, int | bool]:
    nested = plan.count("Nested Loop")
    hash_join = plan.count("Hash Join")
    merge_join = plan.count("Merge Join")
    temp = plan.count(" temp ")
    return {
        "nested_loop_count": nested,
        "hash_join_count": hash_join,
        "merge_join_count": merge_join,
        "temp_spill_hint": temp > 0,
    }


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
        timing = _time_rule_repeated(cur, sql, repeats=5)
        warm_s = timing["warm_wall_seconds_median"]
        warm_times.append(warm_s)
        size_list.append(n)
        _, warm_ms, subplans = _time_rule(cur, sql)
        plan, _, _ = _explain_plan(cur, sql)
        rows_out.append(
            {
                "rows_per_equipment": n,
                "equipment_count": equipment_count,
                "total_history_rows": n * equipment_count,
                "web_mode": web_mode,
                "warm_wall_seconds": warm_s,
                "explain_execution_ms": round(warm_ms, 2),
                "explain_subplan_count": subplans,
                **_plan_join_signals(plan),
                **timing,
            }
        )
    exponent = _growth_exponent(size_list, warm_times)
    segment_slopes: list[dict] = []
    for i in range(len(size_list) - 1):
        seg_exp = _growth_exponent([size_list[i], size_list[i + 1]], [warm_times[i], warm_times[i + 1]])
        segment_slopes.append(
            {
                "from_rows": size_list[i],
                "to_rows": size_list[i + 1],
                "log_log_exponent": None if math.isnan(seg_exp) else round(seg_exp, 4),
            }
        )
    largest = rows_out[-1] if rows_out else {}
    warm_largest = float(largest.get("warm_wall_seconds") or 0.0)
    margin = fdd_timeout_secs - warm_largest
    conn.close()
    return {
        "rule_sql_path": str(RULE_SQL.relative_to(ROOT)),
        "web_asof_bound_seconds": web_asof_bound_seconds,
        "fdd_run_timeout_seconds": fdd_timeout_secs,
        "warm_log_log_exponent": None if math.isnan(exponent) else round(exponent, 4),
        "segment_log_log_slopes": segment_slopes,
        "superlinear_growth": bool(not math.isnan(exponent) and exponent > 1.1),
        "timeout_margin_seconds_largest_case": round(margin, 2),
        "cases": rows_out,
    }


def run_cancellation_recovery(
    *,
    database_url: str,
    web_asof_bound_seconds: float,
    statement_timeout_ms: int = 80,
) -> dict:
    """Prove a timed-out rule attempt releases the session for a follow-up run."""
    sql = _render_rule(web_asof_bound_seconds=web_asof_bound_seconds)
    conn = _connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()
    _setup_fixture(cur, rows_per_equipment=4700, equipment_count=1, web_mode="dense")
    conn.commit()
    cur.execute(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'")
    cancelled = False
    try:
        cur.execute(sql)
        cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — psycopg2 timeout class varies
        conn.rollback()
        cancelled = "timeout" in str(exc).lower() or "cancel" in str(exc).lower()
    cur.execute("RESET statement_timeout")
    conn.commit()
    warm_s, _, _ = _time_rule(cur, sql)
    conn.close()
    return {
        "statement_timeout_ms": statement_timeout_ms,
        "cancel_or_timeout_observed": cancelled,
        "recovery_warm_seconds": round(warm_s, 4),
    }


def _render_base_probe_sql(*, web_asof_bound_seconds: float) -> str:
    """Through ``base`` CTE only — per-sample assessable/raw_fault rows."""
    product = RULE_SQL.read_text(encoding="utf-8").replace("\r\n", "\n")
    web_intervals = product.find("web_intervals AS (")
    base_boundary = product.find("),\nbase AS (")
    elapsed = product.find("),\nelapsed_hold AS (")
    head = product[0:web_intervals]
    joined = product[web_intervals:base_boundary + 2]
    base_body = product[base_boundary + len("),\nbase AS (") : elapsed]
    body = f"{head}{joined}\nbase AS ({base_body})"
    for key, val in {
        "{{WEB_ASOF_BOUND_SECONDS}}": str(web_asof_bound_seconds),
        "{{OAT_ERR}}": "2.777778",
        "{{CONFIRM_SECONDS}}": "900",
        "{{MAX_GAP_HOURS}}": "1.0",
    }.items():
        body = body.replace(key, val)
    return (
        f"{body} "
        "SELECT equipment_id, timestamp_utc, assessable, raw_fault FROM base ORDER BY 1, 2"
    )


def run_mask_boundary_digest(
    *,
    database_url: str,
    web_asof_bound_seconds: float,
) -> dict:
    """Per-point assessable/raw counts on the disposable as-of fixture."""
    probe = _render_base_probe_sql(web_asof_bound_seconds=web_asof_bound_seconds)
    conn = _connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()
    _setup_fixture(cur, rows_per_equipment=700, equipment_count=1, web_mode="sparse")
    cur.execute(
        "SELECT count(*) FILTER (WHERE assessable) AS assessable_rows, "
        "count(*) FILTER (WHERE raw_fault = 1) AS raw_fault_rows, "
        "count(*) AS total_rows "
        f"FROM ({probe}) s"
    )
    row = cur.fetchone()
    conn.close()
    return {
        "assessable_rows": int(row[0]),
        "raw_fault_rows": int(row[1]),
        "total_rows": int(row[2]),
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
