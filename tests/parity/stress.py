#!/usr/bin/env python3
"""Stress / report mode of the SI parity suite: a thin CLI over open_fdd.parity.

    python tests/parity/stress.py --equips 20 --days 14 [--profile basic|edge] [--seed N] [--no-pandas]
                                  [--engines pglite,sqlite] [--out report.json]

generate (open_fdd.parity, alternating healthy / fault-injected equipment, 5-minute grid) -> SQL adapters (PGlite and
SQLite) -> reference (pandas twins via open_fdd.rules) -> compare (shipped Policy and known-difference list). Prints:
rows, per-engine runtime, SQL-side RSS, Python-side peak RSS, pandas runtime, how many rules match, which differ, and
which SQL rules have NO pandas twin. Exit code 1 if an SQL engine errors, the two SQL engines disagree, a rule diverges
from pandas without being in the known-difference list, or fewer rules were compared than have a pandas twin (zero
compared fails). With --no-pandas no pandas verdict is made.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as h  # noqa: E402
from adapters import NodeEngineAdapter  # noqa: E402
from open_fdd.parity import Policy, compare, generate, known_differences, reference  # noqa: E402
from open_fdd.parity.pandas_ref import twin_rule_ids  # noqa: E402


def engines_disagree(results: dict) -> list[str]:
    """Row-level differences between the PGlite and SQLite results (empty = they agree)."""
    bad = []
    for rule, rows in results["pglite"].items():
        left = {h.sql_result_key(r): r for r in rows}
        right = {h.sql_result_key(r): r for r in results["sqlite"].get(rule, [])}
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
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--equips", type=int, default=4)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--profile", default="basic", choices=("basic", "edge"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--engines", default="pglite,sqlite")
    ap.add_argument("--no-pandas", action="store_true", help="SQL engines only (fast; for large --equips/--days)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = ap.parse_args()

    policy = Policy.default(args.profile, stress=True)
    ds = generate(args.seed, args.equips, args.days, args.profile)

    results, errors, timing, memory = {}, {}, {}, {}
    t0 = time.time()
    for kind in args.engines.split(","):
        ad = NodeEngineAdapter(kind)
        ad.load(ds)
        try:
            results[kind] = ad.run()
        finally:
            ad.close()
        errors.update(ad.stats["errors"])
        timing.update(ad.stats["timing"])
        memory.update(ad.stats["memory"])
    sql_wall = time.time() - t0
    rep = {
        "profile": args.profile, "seed": args.seed, "dataset_hash": ds.content_hash(),
        "equips": args.equips, "days": args.days, "rows": len(ds.history),
        "sql_wall_s": round(sql_wall, 2), "sql_timing_ms": timing, "sql_memory_mb": memory, "sql_errors": errors,
    }
    ok = not errors

    if {"pglite", "sqlite"} <= set(results):
        bad = engines_disagree(results)
        rep["pglite_vs_sqlite_mismatches"] = bad
        ok = ok and not bad

    if not args.no_pandas:
        t1 = time.time()
        ref = reference(ds)
        v = compare(results["pglite"], ref, policy)
        twins, no_twin = twin_rule_ids()
        rep["pandas_s"] = round(time.time() - t1, 2)
        listed_all = set(known_differences("all"))
        rep.update({
            "python_peak_rss_mb": round(h.peak_rss_mb(), 1),
            "rules_total": len(twins) + len(no_twin), "rules_with_pandas_twin": v.twins,
            "rules_compared": v.compared, "rules_match": v.matched,
            "rules_diverge": v.diverged, "unexpected_divergence": v.unexpected_rules,
            "now_matching_but_listed": sorted(listed_all - set(v.diverged)),
            "rules_without_pandas_twin": no_twin,
        })
        rep["verdict"] = v.to_dict()
        ok = ok and v.ok
    else:
        rep["python_peak_rss_mb"] = round(h.peak_rss_mb(), 1)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if not args.no_pandas:
        print(v.summary(ok))
    if args.out:
        args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
