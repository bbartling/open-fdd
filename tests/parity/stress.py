#!/usr/bin/env python3
"""Stress / report mode of the SI parity suite.

    python tests/parity/stress.py --equips 20 --days 14 [--no-pandas] [--engines pglite,sqlite] [--out report.json]

Generates a deterministic SI dataset (nf-app/hooks/lib/synthetic_dataset.js: alternating healthy / fault-injected
equipment, 5-minute grid), runs the SQL pack on PGlite and SQLite, runs every rule that has a pandas twin through
open_fdd.rules, and prints: rows, per-engine runtime, SQL-side RSS, Python-side peak RSS, pandas runtime, how many
rules match, which differ, and which SQL rules have NO pandas twin. Exit code 1 only if an SQL engine errors or the two SQL engines
disagree; pandas-vs-SQL divergences are listed (the pytest suite pins the exact set on its 2x3 dataset).
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--equips", type=int, default=4)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--engines", default="pglite,sqlite")
    ap.add_argument("--no-pandas", action="store_true", help="SQL engines only (fast; for large --equips/--days)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = ap.parse_args()

    from test_parity import KNOWN_DIVERGENT  # same documented set as the pytest suite

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
            other = {r["equipment_id"]: r for r in data["results"]["sqlite"].get(rule, [])}
            for r in rows:
                o = other.get(r["equipment_id"])
                for k, v in r.items():
                    w = None if o is None else o.get(k)
                    if isinstance(v, (int, float)) and isinstance(w, (int, float)):
                        if abs(v - w) > 1e-9 + 1e-6 * max(abs(v), abs(w)):
                            bad.append(f"{rule}.{r['equipment_id']}.{k}")
                    elif v != w:
                        bad.append(f"{rule}.{r['equipment_id']}.{k}")
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
            "rules_diverge": diverged, "unexpected_divergence": sorted(set(diverged) - set(KNOWN_DIVERGENT)),
            "now_matching_but_listed": sorted(set(KNOWN_DIVERGENT) - set(diverged)),
            "rules_without_pandas_twin": cmp["no_twin"],
        })
        # divergences are reported, not fatal: the exact KNOWN_DIVERGENT set is only pinned for the pytest dataset
        # (2 equips x 3 days); bigger/longer datasets exercise more branches and may add entries.
    else:
        rep["python_peak_rss_mb"] = round(h.peak_rss_mb(), 1)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
