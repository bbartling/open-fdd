#!/usr/bin/env python3
"""Stress / report mode of the SI parity suite: a thin CLI over open_fdd.parity.

    python tests/parity/stress.py --equips 20 --days 14 [--profile basic|edge] [--seed N] [--no-pandas]
                                  [--engines pglite,sqlite[,duckdb][,postgres][,timescale]] [--out report.json]

generate (open_fdd.parity, alternating healthy / fault-injected equipment, 5-minute grid) -> SQL adapters (PGlite,
SQLite, DuckDB, PostgreSQL, TimescaleDB) -> reference (pandas twins via open_fdd.rules) -> compare (shipped Policy
and known-difference list; on a canonical dataset each known difference must also stay inside its pinned delta band,
see parity_known_differences.json). Exit code 1 if an SQL engine errors, any two SQL engines disagree, a rule diverges
from pandas without being in the known-difference list or leaves its pinned delta band, or fewer rules were compared
than have a pandas twin. With --no-pandas no pandas verdict is made.

``--engines ...,timescale`` defaults to ``ingest="si"`` (loads the exact same SI fixture through ``fdd.point`` /
``fdd.input_sample`` / ``fdd.rule_result`` with identity conversion so it must agree with PGlite row-for-row).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as h  # noqa: E402
from adapters import ADAPTERS, NodeEngineAdapter  # noqa: E402
from open_fdd.parity import Policy, compare, generate, known_differences, reference  # noqa: E402
from open_fdd.parity.pandas_ref import twin_rule_ids  # noqa: E402


BASELINE = HERE / "baseline.json"


def baseline_applies(args) -> dict | None:
    """The pinned verdict when this run uses the baseline's dataset arguments, else None."""
    for p in json.loads(BASELINE.read_text(encoding="utf-8"))["datasets"]:
        if (args.equips, args.days, args.profile, args.seed) == (p["equips"], p["days"], p["profile"], p["seed"]):
            return p["verdict"]
    return None


def _index_rows(rows: list[dict], engine: str, rule: str, bad: list[str]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        key = h.sql_result_key(row)
        if key in indexed:
            bad.append(f"{rule}.{key}: duplicate key in {engine}")
        else:
            indexed[key] = row
    return indexed


def engines_disagree(results: dict, other: str = "sqlite", ref_engine: str = "pglite") -> list[str]:
    """Row-level differences between ``ref_engine`` and ``other``; empty list means exact SI agreement."""
    bad: list[str] = []
    left_rules = results.get(ref_engine, {})
    right_rules = results.get(other, {})
    if set(left_rules) != set(right_rules):
        missing = sorted(set(left_rules) - set(right_rules))
        extra = sorted(set(right_rules) - set(left_rules))
        bad.append(f"rule sets differ ({ref_engine}-only={missing[:5]}, {other}-only={extra[:5]})")

    for rule in sorted(set(left_rules) & set(right_rules)):
        left = _index_rows(left_rules[rule], ref_engine, rule, bad)
        right = _index_rows(right_rules[rule], other, rule, bad)
        if left.keys() != right.keys():
            bad.append(
                f"{rule}: row keys differ ({ref_engine}-only={sorted(left.keys() - right.keys())[:3]}, "
                f"{other}-only={sorted(right.keys() - left.keys())[:3]})"
            )
        for key in sorted(left.keys() & right.keys()):
            r, o = left[key], right[key]
            if set(r) != set(o):
                bad.append(f"{rule}.{key}: columns differ ({sorted(set(r) - set(o))}, {sorted(set(o) - set(r))})")
            for k in sorted(set(r) & set(o)):
                v, w = r.get(k), o.get(k)
                if isinstance(v, float) and not math.isfinite(v):
                    bad.append(f"{rule}.{key}.{k}: nonfinite in {ref_engine} ({v})")
                    continue
                if isinstance(w, float) and not math.isfinite(w):
                    bad.append(f"{rule}.{key}.{k}: nonfinite in {other} ({w})")
                    continue
                if (v is None) != (w is None):
                    bad.append(f"{rule}.{key}.{k}: null vs value ({v!r} vs {w!r})")
                elif isinstance(v, (int, float)) and isinstance(w, (int, float)) and not isinstance(v, bool) and not isinstance(w, bool):
                    if abs(v - w) > 1e-9 + 1e-6 * max(abs(v), abs(w)):
                        bad.append(f"{rule}.{key}.{k}: {v} vs {w}")
                elif v != w:
                    bad.append(f"{rule}.{key}.{k}: {v!r} vs {w!r}")
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

    engine_list = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in engine_list if e not in ADAPTERS]
    if unknown:
        ap.error(f"unknown engine(s) {unknown}; expected subset of {sorted(ADAPTERS)}")
    if not engine_list:
        ap.error("--engines cannot be empty")
    if not args.no_pandas and "pglite" not in engine_list and len(engine_list) == 1:
        pass

    policy = Policy.default(args.profile, stress=True, dataset=f"{args.profile}/{args.seed}/{args.equips}/{args.days}")
    ds = generate(args.seed, args.equips, args.days, args.profile)

    results, errors, timing, memory = {}, {}, {}, {}
    t0 = time.time()
    ts_raw = ts_ad = None
    for kind in engine_list:
        ad = ADAPTERS[kind]()
        ad.load(ds)
        try:
            results[kind] = ad.run()
        finally:
            ad.close()
        errors.update(ad.stats["errors"])
        if kind == "timescale":
            ts_raw, ts_ad = ad.raw, ad
            timing.update({f"timescale_{k}": v for k, v in ad.stats["timing"].items()})
            memory.update({f"timescale_{k}": v for k, v in ad.stats["memory"].items()})
        else:
            timing.update(ad.stats["timing"])
            memory.update(ad.stats["memory"])
    sql_wall = time.time() - t0
    rep = {
        "profile": args.profile, "seed": args.seed, "dataset_hash": ds.content_hash(),
        "equips": args.equips, "days": args.days, "rows": len(ds.history),
        "engines": engine_list,
        "sql_wall_s": round(sql_wall, 2), "sql_timing_ms": timing, "sql_memory_mb": memory, "sql_errors": errors,
    }
    ok = not errors

    ref_sql_engine = "pglite" if "pglite" in results else engine_list[0]
    engine_mismatches = {}
    for kind in engine_list:
        if kind == ref_sql_engine:
            continue
        if kind == "timescale" and ts_raw is not None and ts_raw.get("ingest") == "native":
            continue
        bad = engines_disagree(results, kind, ref_engine=ref_sql_engine)
        engine_mismatches[f"{ref_sql_engine}_vs_{kind}"] = bad
        ok = ok and not bad
    rep["engine_mismatches"] = engine_mismatches
    if {"pglite", "sqlite"} <= set(results):
        rep["pglite_vs_sqlite_mismatches"] = engine_mismatches.get("pglite_vs_sqlite", [])

    if ts_raw is not None:
        ingest_mode = ts_raw.get("ingest", "native")
        if ingest_mode == "si":
            ts_vs_pg = engine_mismatches.get("pglite_vs_timescale", []) if "pglite" in results else ["no pglite run to compare"]
            tie_only = []
        else:
            pg_same = None
            if "pglite" in results:
                same = NodeEngineAdapter("pglite")
                same.load(ts_ad.loaded_dataset(ds))
                try:
                    pg_same = same.run()
                finally:
                    same.close()
            ts_vs_pg = (
                engines_disagree({"pglite": pg_same, "timescale": results["timescale"]}, "timescale", ref_engine="pglite")
                if pg_same is not None else ["no pglite run to compare"]
            )
            tie_only = engines_disagree(results, "timescale", ref_engine="pglite") if "pglite" in results else []
        checks = {
            "ingest": ingest_mode,
            "timescale_vs_pglite_mismatches": ts_vs_pg,
            "threshold_ties_vs_si_dataset": tie_only,
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
        v = compare(results[ref_sql_engine], ref, policy)
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
        rep["known_difference_deltas_h"] = {r: round(d, 4) for r, d in sorted(v.deltas.items())}
        ok = ok and v.ok
        pinned = baseline_applies(args)
        if pinned is not None:
            got = {k: v.to_dict()[k] for k in pinned}
            rep["baseline"] = {"pinned": pinned, "got": got, "ok": got == pinned}
            ok = ok and got == pinned

        verdict_by_engine = {ref_sql_engine: v.to_dict()}
        for kind in engine_list:
            if kind == ref_sql_engine:
                continue
            ve = compare(results[kind], ref, policy)
            ved = ve.to_dict()
            verdict_by_engine[kind] = ved
            if kind == "timescale" and ts_raw is not None and ts_raw.get("ingest") == "native":
                tie_rules = {t.split(":")[0].split(".")[0] for t in rep["timescale"]["threshold_ties_vs_si_dataset"]}
                ved["pin_violations_threshold_ties"] = [p for p in ve.pin_violations if p.split(":")[0] in tie_rules]
                untied = [p for p in ve.pin_violations if p.split(":")[0] not in tie_rules]
                same_verdict = all(ved[k] == v.to_dict()[k] for k in ("compared", "matched", "known_divergent", "unexpected",
                                                                         "unexpected_rules"))
                ok = ok and same_verdict and not untied
            else:
                same_verdict = all(ved[k] == v.to_dict()[k] for k in ("compared", "matched", "known_divergent", "unexpected",
                                                                         "unexpected_rules"))
                ok = ok and ve.ok and same_verdict
        rep["verdict_by_engine"] = verdict_by_engine
        if "timescale" in verdict_by_engine:
            rep["verdict_timescale"] = verdict_by_engine["timescale"]
    else:
        rep["python_peak_rss_mb"] = round(h.peak_rss_mb(), 1)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if not args.no_pandas:
        for line in v.pin_violations:
            print(f"pinned delta out of band: {line}")
        print(v.summary(ok))
    if args.out:
        args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
