#!/usr/bin/env python3
"""Stress / report mode of the SI parity suite: a thin CLI over open_fdd.parity.

    python tests/parity/stress.py --equips 20 --days 14 [--profile basic|edge] [--seed N] [--no-pandas]
                                  [--engines pglite,sqlite[,timescale]] [--out report.json]

generate (open_fdd.parity, alternating healthy / fault-injected equipment, 5-minute grid) -> SQL adapters (PGlite and
SQLite) -> reference (pandas twins via open_fdd.rules) -> compare (shipped Policy and known-difference list). Prints:
rows, per-engine runtime, SQL-side RSS, Python-side peak RSS, pandas runtime, how many rules match, which differ, and
which SQL rules have NO pandas twin. Exit code 1 if an SQL engine errors, the two SQL engines disagree, a rule diverges
from pandas without being in the known-difference list, or fewer rules were compared than have a pandas twin (zero
compared fails). With --no-pandas no pandas verdict is made.

``--engines pglite,sqlite,timescale`` adds the Timescale path through the NEW core tables (fdd.point, fdd.input_sample,
fdd.rule_result; needs PGURL + OPENFDD_TS_TEST_DISPOSABLE=1, see tests/parity/adapters.py). It must agree with PGlite row
for row, load a history equal to the SI dataset cell for cell, write results idempotently, and reproduce the pinned
verdict. For the default dataset (4 equips x 3 days, basic, seed 0) the verdict is pinned in tests/parity/baseline.json.
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
from adapters import NodeEngineAdapter, TimescaleAdapter  # noqa: E402
from open_fdd.parity import Policy, compare, generate, known_differences, reference  # noqa: E402
from open_fdd.parity.pandas_ref import twin_rule_ids  # noqa: E402


BASELINE = HERE / "baseline.json"


def baseline_applies(args) -> dict | None:
    """The pinned verdict when this run uses the baseline's dataset arguments, else None."""
    pinned = json.loads(BASELINE.read_text(encoding="utf-8"))
    p = pinned["dataset"]
    same = (args.equips, args.days, args.profile, args.seed) == (p["equips"], p["days"], p["profile"], p["seed"])
    return pinned["verdict"] if same else None


def engines_disagree(results: dict, other: str = "sqlite") -> list[str]:
    """Row-level differences between the PGlite results and ``other`` (sqlite or timescale); empty = they agree."""
    bad = []
    for rule, rows in results["pglite"].items():
        left = {h.sql_result_key(r): r for r in rows}
        right = {h.sql_result_key(r): r for r in results[other].get(rule, [])}
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
    ts_raw = None
    for kind in args.engines.split(","):
        ad = TimescaleAdapter() if kind == "timescale" else NodeEngineAdapter(kind)
        ad.load(ds)
        try:
            results[kind] = ad.run()
        finally:
            ad.close()
        errors.update(ad.stats["errors"])
        if kind == "timescale":
            ts_raw = ad.raw
            timing.update({f"timescale_{k}": v for k, v in ad.stats["timing"].items()})
            memory.update({f"timescale_{k}": v for k, v in ad.stats["memory"].items()})
        else:
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

    if ts_raw is not None:
        checks = {
            "timescale_vs_pglite_mismatches": engines_disagree(results, "timescale") if "pglite" in results else ["no pglite run to compare"],
            "history_cell_mismatches": ts_raw["history_mismatches"],
            "native_unit_factor_mismatches": ts_raw["factor"]["factor_mismatches"],
            "rerun_added_rows": ts_raw["stored"]["after"] - ts_raw["stored"]["before"],
            "input_sample_signature_ok": ts_raw["signature_ok"], "loader_uses_index": ts_raw["index_ok"],
            "schema_version": ts_raw["schema_version"],
        }
        rep["timescale"] = checks
        clean = not (checks["timescale_vs_pglite_mismatches"] or checks["history_cell_mismatches"]
                     or checks["native_unit_factor_mismatches"] or checks["rerun_added_rows"])
        ok = ok and clean and checks["input_sample_signature_ok"] is True and checks["loader_uses_index"] is True

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
        pinned = baseline_applies(args)
        if pinned is not None:
            got = {k: v.to_dict()[k] for k in pinned}
            rep["baseline"] = {"pinned": pinned, "got": got, "ok": got == pinned}
            ok = ok and got == pinned
        if "timescale" in results:
            vt = compare(results["timescale"], ref, policy)
            rep["verdict_timescale"] = vt.to_dict()
            ok = ok and vt.to_dict() == v.to_dict()
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
