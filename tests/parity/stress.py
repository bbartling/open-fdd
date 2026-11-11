#!/usr/bin/env python3
"""Stress / report mode of the SI parity suite.

    python tests/parity/stress.py --equips 20 --days 14 [--no-pandas] [--engines pglite,sqlite] [--out report.json]

Generates a deterministic SI dataset (nf-app/hooks/lib/synthetic_dataset.js: alternating healthy / fault-injected
equipment, 5-minute grid), runs the SQL pack on PGlite and SQLite, runs every rule that has a pandas twin through
open_fdd.rules, and prints: rows, per-engine runtime, SQL-side RSS, Python-side peak RSS, pandas runtime, how many
rules match, which differ, and which SQL rules have NO pandas twin. Exit code 1 if an SQL engine errors, the two SQL engines disagree, a rule diverges from pandas without being listed in
KNOWN_DIVERGENT, or fewer rules were compared than have a pandas twin (zero compared fails). With --no-pandas no pandas verdict is made.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as h  # noqa: E402


def verdict(compared: int, twins: int, diverged, known) -> dict:
    """Acceptance verdict for the pandas-vs-SQL comparison: fails on any unlisted divergence or a short comparison."""
    diverged = set(diverged)
    unexpected = sorted(diverged - set(known))
    matched = compared - len(diverged)
    return {
        "compared": compared, "matched": matched, "known_divergent": len(diverged & set(known)),
        "unexpected": len(unexpected), "unexpected_rules": unexpected,
        "ok": not unexpected and compared >= twins and compared > 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--equips", type=int, default=4)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--engines", default="pglite,sqlite")
    ap.add_argument("--no-pandas", action="store_true", help="SQL engines only (fast; for large --equips/--days)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = ap.parse_args()

    from test_parity import KNOWN_DIVERGENT, STRESS_ONLY_DIVERGENT  # documented sets, with reasons

    known = set(KNOWN_DIVERGENT) | set(STRESS_ONLY_DIVERGENT)

    tmp = Path(tempfile.mkdtemp(prefix="parity_")) / "sql.json"
    t0 = time.time()
    data = h.run_sql(args.equips, args.days, tmp, engines=args.engines)
    sql_wall = time.time() - t0
    rep = {
        "equips": args.equips, "days": args.days, "rows": data["meta"]["rows"],
        "sql_wall_s": round(sql_wall, 2), "sql_timing_ms": data["timing"], "sql_memory_mb": data["memory"],
        "sql_errors": data["errors"],
    }
    ok = not data["errors"]

    if {"pglite", "sqlite"} <= set(data["results"]):
        bad = []
        for rule, rows in data["results"]["pglite"].items():
            left = {h.sql_result_key(r): r for r in rows}
            right = {h.sql_result_key(r): r for r in data["results"]["sqlite"].get(rule, [])}
            if left.keys() != right.keys():
                bad.append(f"{rule}: row keys differ (pglite-only={sorted(left.keys() - right.keys())[:3]}, "
                           f"sqlite-only={sorted(right.keys() - left.keys())[:3]})")
            for key in sorted(left.keys() & right.keys()):
                r, o = left[key], right[key]
                for k, v in r.items():
                    w = o.get(k)
                    if isinstance(v, (int, float)) and isinstance(w, (int, float)):
                        if abs(v - w) > 1e-9 + 1e-6 * max(abs(v), abs(w)):
                            bad.append(f"{rule}.{key}.{k}")
                    elif v != w:
                        bad.append(f"{rule}.{key}.{k}")
        rep["pglite_vs_sqlite_mismatches"] = bad
        ok = ok and not bad

    if not args.no_pandas:
        t1 = time.time()
        cmp = h.compare(data)
        rep["pandas_s"] = round(time.time() - t1, 2)
        diverged = sorted(r for r, per in cmp["compared"].items() if not h.rule_matches(per))
        rep.update({
            "python_peak_rss_mb": round(h.peak_rss_mb(), 1),
            "rules_total": len(h.CATALOG), "rules_with_pandas_twin": len(cmp["twins"]),
            "rules_compared": len(cmp["compared"]), "rules_match": len(cmp["compared"]) - len(diverged),
            "rules_diverge": diverged, "unexpected_divergence": sorted(set(diverged) - known),
            "now_matching_but_listed": sorted(set(KNOWN_DIVERGENT) - set(diverged)),
            "rules_without_pandas_twin": cmp["no_twin"],
        })
        v = verdict(len(cmp["compared"]), len(cmp["twins"]), diverged, known)
        rep["verdict"] = v
        ok = ok and v["ok"]
    else:
        rep["python_peak_rss_mb"] = round(h.peak_rss_mb(), 1)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if "verdict" in rep:
        v = rep["verdict"]
        print(f"parity: compared={v['compared']} matched={v['matched']} known-divergent={v['known_divergent']} "
              f"unexpected={v['unexpected']} -> {'OK' if ok else 'FAIL'}")
    if args.out:
        args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
