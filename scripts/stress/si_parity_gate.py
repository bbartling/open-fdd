#!/usr/bin/env python3
"""SI parity chain gate — P0–P2 on fixtures/SYNTH; P3 when baseline dir provided (#1284 W3).

CI default (T1284-4):
  python scripts/stress/si_parity_gate.py --fixtures-only

Live P3 (Grok self-hosted stack, not cloud agents):
  python scripts/stress/si_parity_gate.py --stage P3 --baseline-dir ~/openfdd-si-cutover/baseline-… \\
      --sites-config sites.json --jwt-env .env

Fault seconds are exact. Analytics use relative tolerance 1e-6 (see parity_chain.ANALYTICS_REL_TOL).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helpers import EXIT_BLOCKED, EXIT_FAIL, EXIT_PASS, record_check, run_child, safe_print  # noqa: E402
from si_cutover import parity_chain as pc  # noqa: E402


def run_fixtures_only() -> int:
    results = pc.run_fixture_stages()
    total, errors = pc.summarize(results)
    for r in results:
        safe_print(
            f"  {r.stage}: comparisons={r.comparisons} "
            f"{'OK' if not r.errors else 'FAIL ' + '; '.join(r.errors[:3])}"
        )
        if r.comparisons > 0 and not r.errors:
            record_check(f"si_parity.{r.stage}", True, comparisons=r.comparisons)
        elif r.errors:
            record_check(f"si_parity.{r.stage}", False, comparisons=r.comparisons)
    if errors:
        safe_print(f"FAIL si-parity: {len(errors)} error(s); first: {errors[0]}")
        return EXIT_FAIL
    if total < 1:
        safe_print("BLOCKED si-parity: zero comparisons")
        return EXIT_BLOCKED
    per_stage = [r for r in results if r.comparisons > 0]
    if len(per_stage) < 3:
        safe_print(f"BLOCKED si-parity: need nonzero counts in P0/P1/P2 stages, got {len(per_stage)}")
        return EXIT_BLOCKED
    safe_print(f"PASS si-parity fixtures ({total} comparisons across {len(per_stage)} stages)")
    return EXIT_PASS


def run_t1284_4_mutation_self_test() -> int:
    """Deliberate unit scale mutation must fail unit vector verification."""
    metric = pc._metric_doc()
    mutated = copy.deepcopy(metric)
    rows = mutated.get("source_unit_conversions") or []
    for row in rows:
        if row.get("alias") == "degF":
            row["scale"] = float(row["scale"]) * 1.001
            break
    else:
        safe_print("FAIL T1284-4: could not find degF alias to mutate")
        return EXIT_FAIL

    cases = json.loads(pc.UNIT_VECTORS.read_text(encoding="utf-8")).get("cases") or []
    errors: list[str] = []
    comparisons = 0
    for case in cases:
        comparisons += 1
        try:
            got = pc.uc.convert_to_canonical(
                mutated, case["quantity"], float(case["input"]), case["source_unit"]
            )
        except ValueError:
            continue
        expect = float(case["metric"])
        tol = float(case.get("tol", 1e-9))
        if abs(got - expect) <= tol:
            safe_print(
                f"FAIL T1284-4: mutation did not break case {case['id']} (got {got} ~ {expect})"
            )
            return EXIT_FAIL
    if comparisons < 1:
        safe_print("FAIL T1284-4: no cases exercised")
        return EXIT_FAIL
    safe_print(f"PASS T1284-4 mutation guard ({comparisons} temperature cases rejected)")
    record_check("T1284-4.unit_mutation", True, comparisons=comparisons)
    return EXIT_PASS


def run_p3_cli(args: argparse.Namespace) -> int:
    # Offline fixture mode for unit tests
    if args.p3_fixture:
        fixture = pc.P3_BASELINE_FIXTURE
        site_dir = fixture / "SITE_MINI"
        live_sql = list(pc.iter_jsonl_gz(site_dir / "live_sql_si_daily.jsonl.gz"))
        live_counts = list(pc.iter_jsonl_gz(site_dir / "live_sample_counts.jsonl.gz"))
        result = pc.compare_p3_post_cutover(
            baseline_dir=fixture,
            building_id="SITE_MINI",
            live_sql_daily=live_sql,
            live_sample_counts=live_counts,
        )
        if result.errors:
            safe_print(f"FAIL P3 fixture: {'; '.join(result.errors)}")
            return EXIT_FAIL
        if result.comparisons < 1:
            safe_print("BLOCKED P3 fixture: zero comparisons")
            return EXIT_BLOCKED
        record_check("si_parity.P3", True, comparisons=result.comparisons)
        safe_print(f"PASS P3 fixture ({result.comparisons} comparisons)")
        return EXIT_PASS
    if not args.baseline_dir or not args.sites_config:
        safe_print("BLOCKED P3: --baseline-dir and --sites-config required")
        return EXIT_BLOCKED
    sites = json.loads(Path(args.sites_config).read_text(encoding="utf-8"))
    if not isinstance(sites, list):
        safe_print("FAIL P3: sites-config must be a JSON list")
        return EXIT_FAIL
    safe_print(
        "BLOCKED P3 live: Grok bot runs post-cutover compare on the owner stack; "
        "cloud agents validate --p3-fixture only"
    )
    return EXIT_BLOCKED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fixtures-only",
        action="store_true",
        help="Run P0–P2 offline against repo fixtures (CI default)",
    )
    ap.add_argument(
        "--mutation-self-test",
        action="store_true",
        help="T1284-4: verify deliberate unit mutation fails parity",
    )
    ap.add_argument("--stage", choices=("P3",), help="Run live P3 only")
    ap.add_argument("--baseline-dir", type=Path, help="W0b baseline output directory")
    ap.add_argument("--sites-config", type=Path, help="JSON list of sites for P3")
    ap.add_argument(
        "--p3-fixture",
        action="store_true",
        help="Compare against tests/fixtures/si_cutover/p3_baseline_mini (unit test path)",
    )
    args = ap.parse_args(argv)

    if args.mutation_self_test:
        return run_t1284_4_mutation_self_test()
    if args.stage == "P3":
        return run_p3_cli(args)
    if args.fixtures_only or not any(
        (args.mutation_self_test, args.stage, args.p3_fixture)
    ):
        return run_fixtures_only()
    ap.error("no mode selected")


if __name__ == "__main__":
    raise SystemExit(run_child(main, "si_parity_gate.py"))
