#!/usr/bin/env python3
"""SI parity chain gate — P0–P2 on fixtures/SYNTH; P3 when baseline dir provided (#1284 W3).

CI default (full matrix, report-only mismatches):
  python scripts/stress/si_parity_gate.py --fixtures-only --report-json si_parity_report.json

Blocking W4 family (W4a AHU fault conditions):
  python scripts/stress/si_parity_gate.py --fixtures-only --blocking --family W4a_si_ahu_fc
Blocking W4 family (W4b AHU economizer):
  python scripts/stress/si_parity_gate.py --fixtures-only --blocking --family W4b_ahu_econ

Blocking W4f analytics family (19 analytics queries, P1/P2-analytics):
  python scripts/stress/si_parity_gate.py --fixtures-only --blocking --family W4f_analytics_si_p2

T1284-4 gate failure under mutation + blocking scope:
  python scripts/stress/si_parity_gate.py --fixtures-only --blocking --rules FC1 --inject-t1284-4-mutation
  python scripts/stress/si_parity_gate.py --fixtures-only --blocking --family W4f_analytics_si_p2 --inject-t1284-4-mutation

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
from si_cutover import analytics_parity as ap  # noqa: E402
from si_cutover import ci_fixtures_lib as cfl  # noqa: E402
from si_cutover.si_parity_families import (  # noqa: E402
    SI_SQL_PACK_FAMILIES,
    resolve_analytics_scope,
    resolve_rule_scope,
)


def _print_mismatch_table(label: str, table: dict[str, int], *, limit: int = 20) -> None:
    if not table:
        safe_print(f"  {label}: (no rule-level mismatches)")
        return
    safe_print(f"  {label} mismatches by rule_id (top {limit}):")
    for rid, count in sorted(table.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        safe_print(f"    {rid}: {count}")


def _print_p0_kind_table(p0: pc.StageResult) -> None:
    kinds: dict[str, int] = {}
    for cell in p0.structured:
        k = str(cell.get("kind") or "other")
        kinds[k] = kinds.get(k, 0) + 1
    safe_print(
        f"  P0 by kind: sql_row_missing={kinds.get('sql_row_missing', 0)} "
        f"value_mismatch={kinds.get('value_mismatch', 0)} "
        f"ip_sql_skipped_si_pack={kinds.get('ip_sql_skipped_si_pack', 0)}"
    )


def _scope_label(scope: set[str] | None, *, family: str | None, rules: tuple[str, ...]) -> str:
    if family:
        return f"family:{family}"
    if rules:
        return f"rules:{','.join(rules)}"
    return "full_matrix"


def _blocking_errors(
    results: list[pc.StageResult],
    *,
    blocking: bool,
    scope: set[str] | None,
) -> list[str]:
    """Structural gate: P0 never blocks; scoped P1/P2 (rule and analytics) mismatches
    block under --blocking. The full matrix without --blocking is report-only so
    rules/queries not yet migrated by their W4 row do not block (W6 requires green)."""
    out: list[str] = []
    always_block = ("unit_vectors", "unit_scenarios", "pandas-errors", "P0-carryover")
    for r in results:
        if r.stage in always_block:
            out.extend(r.errors)
            continue
        if not blocking:
            continue
        if r.stage in ("P1-analytics", "P2-analytics"):
            out.extend(r.errors)
        elif scope is not None and r.stage in ("P1", "P2"):
            out.extend(r.errors)
        if scope is not None and r.stage == "P2" and r.pending:
            # A scoped blocking family gate may not pass on cells it never compared.
            out.append(
                f"P2: {r.pending} cell(s) pending_W4 in blocking scope (must be zero)"
            )
    return out


def _fc1_t1284_si_param_post_hook(rule_id: str, params: dict[str, float]) -> dict[str, float]:
    if rule_id != "FC1":
        return params
    return cfl.t1284_break_eps_dsp_si(params, rule_id=rule_id)


def run_fixtures_gate(
    *,
    scope: set[str] | None,
    scope_label: str,
    blocking: bool,
    family: str | None,
    report_json: Path | None,
    inject_t1284_4: bool,
    analytics_scope: set[str] | None = None,
) -> int:
    analytics_mutation = inject_t1284_4 and analytics_scope != set()
    si_post = _fc1_t1284_si_param_post_hook if inject_t1284_4 and not analytics_mutation else None
    strict_p2 = bool(blocking and family in SI_SQL_PACK_FAMILIES)
    rules_in_scope = scope is None or bool(scope)
    results = (
        pc.run_fixture_stages(scope=scope, strict_p2=strict_p2, si_param_post_hook=si_post)
        if rules_in_scope
        else []
    )
    analytics_results: list[pc.StageResult] = []
    if analytics_scope != set():
        if analytics_mutation:
            baseline = list(ap.run_analytics_stages(scope=analytics_scope))
            baseline_map = {r.stage: r for r in baseline}
            required = (baseline_map.get("P1-analytics"), baseline_map.get("P2-analytics"))
            if any(r is None or r.comparisons <= 0 or r.errors for r in required):
                details = [
                    f"{r.stage if r else 'missing stage'}: comparisons={r.comparisons if r else 0}, "
                    f"errors={len(r.errors) if r else 'missing'}"
                    for r in required
                ]
                safe_print(
                    "FAIL T1284-4: analytics positive control must have nonzero comparisons "
                    "and no errors before mutation credit (" + "; ".join(details) + ")"
                )
                return EXIT_FAIL
            baseline_comparisons = sum(r.comparisons for r in required if r is not None)
            record_check(
                "T1284-4.analytics_positive_control",
                True,
                comparisons=baseline_comparisons,
            )
        hook = ap.t1284_4_analytics_double_conversion if analytics_mutation else None
        analytics_results = list(ap.run_analytics_stages(scope=analytics_scope, param_hook=hook))
    stage_map = {r.stage: r for r in results + analytics_results}

    p0 = stage_map.get("P0")
    p1 = stage_map.get("P1")
    p2 = stage_map.get("P2")
    p0_n = p0.comparisons if p0 else 0
    p1_n = p1.comparisons if p1 else 0
    p2_n = p2.comparisons if p2 else 0
    p0_m = len(p0.errors) if p0 else 0
    p1_m = len(p1.errors) if p1 else 0
    safe_print(
        f"  scope={scope_label} blocking={blocking} inject_t1284_4={inject_t1284_4}"
    )
    safe_print(
        f"  P0 comparisons={p0_n} mismatches={p0_m}  "
        f"P1 comparisons={p1_n} mismatches={p1_m}  "
        f"P2 comparisons={p2_n} pending_W4={p2.pending if p2 else 0}"
    )

    if p0 and p0.errors:
        _print_p0_kind_table(p0)
        _print_mismatch_table("P0 value_mismatch", pc.rule_mismatch_table(p0.errors, stage="P0"))
    if p0 and p0.mismatch_table:
        for line in p0.mismatch_table:
            safe_print(f"  {line}")
    if p1 and p1.errors:
        _print_mismatch_table("P1", pc.rule_mismatch_table(p1.errors, stage="P1"))

    if p2 and p2.mismatch_table:
        for line in p2.mismatch_table:
            safe_print(f"  {line}")
    for ar in analytics_results:
        safe_print(f"  {ar.stage} comparisons={ar.comparisons} mismatches={len(ar.errors)}")
        for line in ar.errors[:20]:
            safe_print(f"    {line[:200]}")

    report = pc.build_si_parity_report(
        results, scope=scope, scope_label=scope_label, blocking=blocking
    )
    report["analytics"] = {
        "scope_queries": sorted(analytics_scope) if analytics_scope is not None else ["*"],
        "rel_tol": pc.ANALYTICS_REL_TOL,
        "stages": {
            ar.stage: {
                "comparisons": ar.comparisons,
                "mismatch_count": len(ar.errors),
                "mismatches": list(ar.errors),
                "coverage": list(ar.structured),
            }
            for ar in analytics_results
        },
    }
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        safe_print(f"  wrote {report_json}")

    for r in results:
        if r.stage in ("P0", "P1") and r.comparisons > 0:
            if r.stage == "P0":
                # P0 is report-only even under --blocking + scope.
                record_check(f"si_parity.{r.stage}", True, comparisons=r.comparisons)
            else:
                record_check(
                    f"si_parity.{r.stage}",
                    not (blocking and r.errors and scope is not None),
                    comparisons=r.comparisons,
                )
        elif r.comparisons > 0 and not r.errors:
            record_check(f"si_parity.{r.stage}", True, comparisons=r.comparisons)
        elif r.errors and blocking:
            record_check(f"si_parity.{r.stage}", False, comparisons=r.comparisons)

    for ar in analytics_results:
        record_check(
            f"si_parity.{ar.stage}",
            ar.comparisons > 0 and not (blocking and ar.errors),
            comparisons=ar.comparisons,
        )

    gate_failures = _blocking_errors(results + analytics_results, blocking=blocking, scope=scope)

    if analytics_mutation:
        if not blocking or analytics_scope is None and scope is None:
            safe_print(
                "FAIL T1284-4: analytics mutation requires --blocking and a family that owns analytics queries"
            )
            return EXIT_FAIL
        ap1 = stage_map.get("P1-analytics")
        if not ap1 or ap1.comparisons <= 0 or not ap1.errors:
            safe_print(
                "FAIL T1284-4: analytics mutation must produce P1-analytics mismatches "
                "with nonzero comparisons"
            )
            return EXIT_FAIL
        safe_print(
            f"PASS T1284-4 blocking gate failure under analytics mutation "
            f"(P1-analytics mismatches={len(ap1.errors)} e.g. {ap1.errors[0][:100]})"
        )
        record_check("T1284-4.blocking_mutation", True, comparisons=ap1.comparisons)
        return EXIT_FAIL

    if inject_t1284_4:
        if scope is None or "FC1" not in scope:
            safe_print("FAIL T1284-4: --inject-t1284-4-mutation requires FC1 in scope (--rules FC1)")
            return EXIT_FAIL
        if not blocking:
            safe_print("FAIL T1284-4: --inject-t1284-4-mutation requires --blocking")
            return EXIT_FAIL
        p1 = stage_map.get("P1")
        if not p1 or not p1.errors:
            safe_print("FAIL T1284-4: mutation did not produce scoped P1 mismatches")
            return EXIT_FAIL
        safe_print(
            f"PASS T1284-4 blocking gate failure under mutation "
            f"(P1 mismatches={len(p1.errors)} e.g. {p1.errors[0][:80]})"
        )
        record_check("T1284-4.blocking_mutation", True, comparisons=p1.comparisons)
        return EXIT_FAIL

    if gate_failures:
        safe_print(f"FAIL si-parity (blocking): {len(gate_failures)} error(s); first: {gate_failures[0]}")
        return EXIT_FAIL

    if blocking and (scope is not None or analytics_scope is not None):
        required_stages = (("P0", "P1", "P2") if rules_in_scope else ()) + (
            ("P1-analytics", "P2-analytics") if analytics_results else ()
        )
        if not required_stages:
            safe_print("BLOCKED si-parity: scope owns no rules and no analytics queries")
            return EXIT_BLOCKED
        for required in required_stages:
            st = stage_map.get(required)
            if st is None or st.comparisons < 1:
                safe_print(f"BLOCKED si-parity: scoped stage {required} needs nonzero comparisons")
                return EXIT_BLOCKED
        safe_print(f"PASS si-parity blocking scope={scope_label}")
        return EXIT_PASS

    for required in ("P0", "P1", "P2", "P1-analytics", "P2-analytics"):
        st = stage_map.get(required)
        if st is None or st.comparisons < 1:
            safe_print(f"BLOCKED si-parity: stage {required} needs nonzero comparisons")
            return EXIT_BLOCKED
    safe_print(
        f"PASS si-parity fixtures report-only (P0={p0_n}/{p0_m} P1={p1_n}/{p1_m} P2={p2_n} "
        f"P2 mismatches={len(p2.errors) if p2 else 0}; full-matrix mismatches logged + si_parity_report.json)"
    )
    return EXIT_PASS


def run_t1284_4_mutation_self_test() -> int:
    """Deliberate unit scale mutation must fail unit vectors; rule SI mutation must fail P1."""
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
    vector_checks = 0
    for case in cases:
        vector_checks += 1
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
                f"FAIL T1284-4: contract mutation did not break case {case['id']} (got {got} ~ {expect})"
            )
            return EXIT_FAIL
    broken = pc.verify_unit_vector_goldens(mutated)
    if not broken.errors:
        safe_print("FAIL T1284-4: mutated contract did not fail unit_vectors parity")
        return EXIT_FAIL

    goldens = pc.load_all_ip_goldens()
    p1_broken = pc.run_t1284_4_rule_mutation_p1(goldens)
    if not p1_broken.errors or not any("P1 FC1" in e for e in p1_broken.errors):
        safe_print("FAIL T1284-4: FC1 SI param unit mutation did not fail P1 parity")
        return EXIT_FAIL

    a_p1, _a_p2 = ap.run_analytics_stages(
        scope=None, param_hook=ap.t1284_4_analytics_double_conversion
    )
    if not a_p1.errors:
        safe_print("FAIL T1284-4: analytics SI param unit mutation did not fail P1-analytics")
        return EXIT_FAIL

    safe_print(
        f"PASS T1284-4 mutation guard ({vector_checks} vector cases; "
        f"P1-analytics failures={len(a_p1.errors)}; "
        f"P1 failures={len(p1_broken.errors)} e.g. {p1_broken.errors[0][:72]})"
    )
    record_check("T1284-4.unit_mutation", True, comparisons=vector_checks + p1_broken.comparisons)
    return EXIT_PASS


def run_p3_cli(args: argparse.Namespace) -> int:
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


def _parse_rules_arg(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(r.strip() for r in raw.split(",") if r.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fixtures-only",
        action="store_true",
        help="Run P0–P2 offline against repo fixtures (CI default)",
    )
    ap.add_argument(
        "--blocking",
        action="store_true",
        help="Inside scope, P1/P2 mismatches fail the gate (P0 is always report-only)",
    )
    ap.add_argument(
        "--rules",
        metavar="ID,...",
        help="Scope parity to comma-separated rule ids (e.g. FC1)",
    )
    ap.add_argument(
        "--family",
        help="Scope parity to a W4 family from tests/fixtures/si_cutover/w4_parity_families.json",
    )
    ap.add_argument(
        "--report-json",
        type=Path,
        help="Write structured si_parity_report.json (full matrix in CI)",
    )
    ap.add_argument(
        "--inject-t1284-4-mutation",
        action="store_true",
        help="Mutate SI params (analytics OAT bin edges for a family owning analytics queries, "
        "else FC1); with --blocking expect exit 1",
    )
    ap.add_argument(
        "--mutation-self-test",
        action="store_true",
        help="T1284-4: verify deliberate unit mutation fails parity (unit vectors + FC1 probe)",
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

    rules_tuple = _parse_rules_arg(args.rules)
    try:
        scope = resolve_rule_scope(rules=rules_tuple or None, family=args.family)
        analytics_scope = set() if rules_tuple else resolve_analytics_scope(args.family)
    except (ValueError, KeyError) as exc:
        safe_print(f"FAIL si-parity scope: {exc}")
        return EXIT_FAIL

    if args.fixtures_only or not any((args.mutation_self_test, args.stage, args.p3_fixture)):
        scope_label = _scope_label(scope, family=args.family, rules=rules_tuple)
        return run_fixtures_gate(
            scope=scope,
            scope_label=scope_label,
            blocking=bool(args.blocking),
            family=args.family,
            report_json=args.report_json,
            inject_t1284_4=bool(args.inject_t1284_4_mutation),
            analytics_scope=analytics_scope,
        )
    ap.error("no mode selected")


if __name__ == "__main__":
    raise SystemExit(run_child(main, "si_parity_gate.py"))
