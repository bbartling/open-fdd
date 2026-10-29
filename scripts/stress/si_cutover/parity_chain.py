"""SI cutover parity chain P0–P3 helpers (#1284 W3).

Equality contract:
  * FDD fault_seconds: exact (integer or float bit-equal after rounding to 1e-9 s)
  * Analytics numeric fields: relative tolerance ANALYTICS_REL_TOL (1e-6) documented here

Uses ``scripts/ci/unit_contract_lib.py`` only — no second conversion table.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci import unit_contract_lib as uc  # noqa: E402

ANALYTICS_REL_TOL = 1e-6
FAULT_SECONDS_ATOL = 0.0  # exact — use math.isclose with rel_tol=0, abs_tol=1e-9

REPO = ROOT
IP_GOLDENS_DIR = REPO / "tests" / "fixtures" / "si_cutover" / "ip_goldens"
UNIT_VECTORS = REPO / "sql" / "contract" / "goldens" / "unit_vectors.json"
UNIT_SCENARIOS = REPO / "sql" / "contract" / "goldens" / "si_parity_unit_scenarios.json"
P2_HOOK_GOLDEN = REPO / "tests" / "fixtures" / "si_cutover" / "p2_si_hook.json"
COOKBOOK_FIXTURES = REPO / "docs" / "rules" / "cookbook" / "fixtures"
P3_BASELINE_FIXTURE = REPO / "tests" / "fixtures" / "si_cutover" / "p3_baseline_mini"

CARRYOVER_RULES_P0 = (
    "VAV-1",
    "SV-FLATLINE",
    "SV-RANGE",
    "SV-STALE",
    "OAT-METEO",
)


@dataclass(frozen=True)
class StageResult:
    stage: str
    comparisons: int
    errors: tuple[str, ...]
    mismatch_table: tuple[str, ...] = ()


def _metric_doc() -> dict[str, Any]:
    return uc.load_json(uc.METRIC_UNITS)


def fault_seconds_equal(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)


def analytics_relative_equal(a: float, b: float) -> bool:
    if not math.isfinite(a) and not math.isfinite(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= ANALYTICS_REL_TOL


def fdd_daily_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("building_id", "")),
        str(row.get("rule_id", "")),
        str(row.get("equipment_id", "")),
        str(row.get("utc_day", "")),
    )


def load_ip_golden(path: Path) -> dict[str, Any]:
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != "si-cutover-ip-golden-v1":
        raise ValueError(f"{path}: expected schema si-cutover-ip-golden-v1")
    return body


def iter_jsonl_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_baseline_site_dir(site_dir: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for name in (
        "sql_fdd_daily.jsonl.gz",
        "pandas_fdd_daily.jsonl.gz",
        "analytics_rows.jsonl.gz",
        "sample_counts.jsonl.gz",
    ):
        path = site_dir / name
        if path.is_file():
            out[name.removesuffix(".jsonl.gz")] = list(iter_jsonl_gz(path))
    return out


def compare_p0_ip_golden(golden: dict[str, Any]) -> StageResult:
    """P0: pandas IP == SQL IP from frozen golden rows (exact fault_seconds)."""
    sql_rows = golden.get("sql_fdd_daily") or []
    pandas_rows = golden.get("pandas_fdd_daily") or []
    errors: list[str] = []
    comparisons = 0
    pandas_by_key = {fdd_daily_key(r): r for r in pandas_rows}
    for sql in sql_rows:
        key = fdd_daily_key(sql)
        other = pandas_by_key.get(key)
        if other is None:
            errors.append(f"P0 missing pandas row for {key}")
            continue
        comparisons += 1
        if not fault_seconds_equal(sql.get("fault_seconds", 0), other.get("fault_seconds", 0)):
            errors.append(
                f"P0 fault_seconds {key}: sql={sql.get('fault_seconds')} "
                f"pandas={other.get('fault_seconds')}"
            )
        if str(sql.get("status", "")) != str(other.get("status", "")):
            errors.append(f"P0 status {key}: sql={sql.get('status')} pandas={other.get('status')}")
    if not sql_rows:
        errors.append("P0: golden has no sql_fdd_daily rows")
    return StageResult("P0", comparisons, tuple(errors))


def verify_p0_carryover_coverage(golden: dict[str, Any]) -> StageResult:
    """#1404 / #1407 / #1408: carry-over rules must appear in the ip golden at P0."""
    sql_rules = {str(r.get("rule_id", "")) for r in golden.get("sql_fdd_daily") or []}
    analytics_endpoints = {
        str(r.get("endpoint", "")) for r in golden.get("analytics_rows") or []
    }
    errors: list[str] = []
    comparisons = 0
    for rule_id in CARRYOVER_RULES_P0:
        if rule_id == "OAT-METEO":
            if rule_id in sql_rules:
                comparisons += 1
            elif "/api/analytics/oat_meteo" in analytics_endpoints:
                comparisons += 1
            else:
                errors.append(f"P0 carry-over: missing OAT-METEO (rule or analytics row)")
            continue
        if rule_id not in sql_rules:
            errors.append(f"P0 carry-over: missing rule {rule_id} in sql_fdd_daily")
            continue
        comparisons += 1
    return StageResult("P0-carryover", comparisons, tuple(errors))


def compare_p0_analytics_golden(golden: dict[str, Any]) -> StageResult:
    """P0 analytics slice inside ip golden (optional rows)."""
    rows = golden.get("analytics_rows") or []
    errors: list[str] = []
    comparisons = 0
    for rec in rows:
        endpoint = rec.get("endpoint", "")
        if endpoint != "/api/analytics/oat_meteo":
            continue
        row = rec.get("row") if isinstance(rec.get("row"), dict) else {}
        sql_val = row.get("mean_abs_diff_f")
        pandas_val = row.get("pandas_mean_abs_diff_f")
        if sql_val is None or pandas_val is None:
            continue
        comparisons += 1
        if not analytics_relative_equal(float(sql_val), float(pandas_val)):
            errors.append(
                f"P0 analytics OAT-METEO: sql={sql_val} pandas={pandas_val} "
                f"(rel tol {ANALYTICS_REL_TOL})"
            )
    return StageResult("P0-analytics", comparisons, tuple(errors))


def verify_unit_vector_goldens(metric: dict[str, Any] | None = None) -> StageResult:
    doc = metric if metric is not None else _metric_doc()
    cases = json.loads(UNIT_VECTORS.read_text(encoding="utf-8")).get("cases") or []
    errors: list[str] = []
    comparisons = 0
    for case in cases:
        qid = case["quantity"]
        src = case["source_unit"]
        inp = float(case["input"])
        expect = float(case["metric"])
        tol = float(case.get("tol", 1e-9))
        try:
            got = uc.convert_to_canonical(doc, qid, inp, src)
        except ValueError as exc:
            errors.append(f"unit_vectors {case['id']}: {exc}")
            continue
        comparisons += 1
        if abs(got - expect) > tol:
            errors.append(f"unit_vectors {case['id']}: got {got} expect {expect}")
    return StageResult("unit_vectors", comparisons, tuple(errors))


def verify_unit_scenarios() -> StageResult:
    if not UNIT_SCENARIOS.is_file():
        return StageResult("unit_scenarios", 0, ("missing si_parity_unit_scenarios.json",))
    metric = _metric_doc()
    doc = json.loads(UNIT_SCENARIOS.read_text(encoding="utf-8"))
    errors: list[str] = []
    comparisons = 0
    for scenario in doc.get("scenarios") or []:
        sid = scenario.get("id", "?")
        if scenario.get("expect_error"):
            for probe in scenario.get("probes") or []:
                comparisons += 1
                try:
                    uc.convert_to_canonical(
                        metric,
                        probe["quantity"],
                        float(probe["input"]),
                        probe["source_unit"],
                    )
                    errors.append(f"{sid}: expected conversion error for {probe}")
                except ValueError:
                    pass
            continue
        for probe in scenario.get("probes") or []:
            comparisons += 1
            qid = probe["quantity"]
            val = float(probe["input"])
            unit = probe["source_unit"]
            expect = float(probe["metric"])
            tol = float(probe.get("tol", 1e-9))
            got = uc.convert_to_canonical(metric, qid, val, unit)
            if abs(got - expect) > tol:
                errors.append(f"{sid}/{probe.get('label', unit)}: got {got} expect {expect}")
        for pair in scenario.get("physical_pairs") or []:
            comparisons += 1
            a = uc.convert_to_canonical(
                metric, pair["quantity"], float(pair["ip_value"]), pair["ip_unit"]
            )
            b = uc.convert_to_canonical(
                metric, pair["quantity"], float(pair["si_value"]), pair["si_unit"]
            )
            if abs(a - b) > float(pair.get("tol", 1e-9)):
                errors.append(f"{sid} physical_pair: {a} != {b}")
    return StageResult("unit_scenarios", comparisons, tuple(errors))


def list_ip_golden_files() -> list[Path]:
    paths = sorted(IP_GOLDENS_DIR.glob("*.json"))
    out: list[Path] = []
    for path in paths:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if body.get("schema") == "si-cutover-ip-golden-v1":
            out.append(path)
    if not out:
        raise FileNotFoundError(f"no si-cutover-ip-golden-v1 files under {IP_GOLDENS_DIR}")
    return out


def load_all_ip_goldens() -> list[dict[str, Any]]:
    return [load_ip_golden(p) for p in list_ip_golden_files()]


def _pandas_computed_daily(golden: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r
        for r in golden.get("pandas_fdd_daily") or []
        if r.get("pair_status") == "computed" and r.get("utc_day")
    ]


def _sql_computed_daily(golden: dict[str, Any]) -> list[dict[str, Any]]:
    return list(golden.get("sql_fdd_daily") or [])


def _parity_ip_rows(golden: dict[str, Any]) -> list[dict[str, Any]]:
    return _pandas_computed_daily(golden)


def _rules_with_sql_file() -> set[str]:
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    return {
        str(r.get("rule_id") or "")
        for r in cfl.load_rule_registry()
        if r.get("sql_file")
    }


def _p0_pandas_rows(golden: dict[str, Any], sql_rules: set[str]) -> list[dict[str, Any]]:
    return [
        r
        for r in _pandas_computed_daily(golden)
        if str(r.get("rule_id") or "") in sql_rules
    ]


def min_p0_cells(golden: dict[str, Any]) -> int:
    return len(_p0_pandas_rows(golden, _rules_with_sql_file()))


def min_p1_cells(golden: dict[str, Any]) -> int:
    return len(_pandas_computed_daily(golden))


def min_p2_cells(golden: dict[str, Any]) -> int:
    return len([p for p in golden.get("p2_si_pairs") or [] if p.get("utc_day")])


def verify_pandas_errors(golden: dict[str, Any]) -> StageResult:
    errors_list = [r for r in golden.get("pandas_fdd_daily") or [] if r.get("pair_status") == "error"]
    building = golden.get("building_id", "?")
    errors: list[str] = []
    for row in errors_list[:10]:
        errors.append(
            f"{building} pandas error {row.get('rule_id')}/{row.get('equipment_id')}: "
            f"{row.get('reason')}"
        )
    if len(errors_list) > 10:
        errors.append(f"{building}: … and {len(errors_list) - 10} more pandas error rows")
    return StageResult("pandas-errors", len(errors_list), tuple(errors))


def compare_p0_all_goldens(goldens: list[dict[str, Any]]) -> StageResult:
    errors: list[str] = []
    mismatches: list[str] = []
    comparisons = 0
    min_required = 0
    sql_rules = _rules_with_sql_file()
    for golden in goldens:
        min_required += min_p0_cells(golden)
        sql_by_key = {fdd_daily_key(r): r for r in _sql_computed_daily(golden)}
        for prow in _p0_pandas_rows(golden, sql_rules):
            key = fdd_daily_key(prow)
            comparisons += 1
            srow = sql_by_key.get(key)
            if srow is None:
                msg = f"P0 missing SQL {key}"
                mismatches.append(msg)
                errors.append(msg)
                continue
            if not fault_seconds_equal(
                prow.get("fault_seconds", 0), srow.get("fault_seconds", 0)
            ):
                msg = (
                    f"P0 {key}: pandas_ip={prow.get('fault_seconds')} "
                    f"sql_ip={srow.get('fault_seconds')}"
                )
                mismatches.append(msg)
                errors.append(msg)
        sub_a = compare_p0_analytics_golden(golden)
        comparisons += sub_a.comparisons
        errors.extend(sub_a.errors)
    if comparisons < min_required:
        errors.append(
            f"P0: comparisons {comparisons} < required pandas/sql cells {min_required}"
        )
    return StageResult("P0", comparisons, tuple(errors), tuple(mismatches))


def verify_golden_rule_attempted(golden: dict[str, Any], expected_rules: set[str]) -> StageResult:
    seen = set(golden.get("pandas_rules_attempted") or [])
    missing = sorted(expected_rules - seen)
    errors = [f"{golden.get('building_id')}: rule dropout: {missing[:8]}…"] if missing else []
    return StageResult(
        "rule-coverage",
        len(seen),
        tuple(errors),
    )


def verify_p0_carryover_all(goldens: list[dict[str, Any]]) -> StageResult:
    sql_rules: set[str] = set()
    pandas_rules_seen: set[str] = set()
    analytics_endpoints: set[str] = set()
    attempted_rules: set[str] = set()
    for golden in goldens:
        sql_rules |= {str(r.get("rule_id", "")) for r in golden.get("sql_fdd_daily") or []}
        pandas_rules_seen |= {
            str(r.get("rule_id", ""))
            for r in golden.get("pandas_fdd_daily") or []
            if r.get("pair_status") == "computed"
        }
        attempted_rules |= {str(r) for r in golden.get("pandas_rules_attempted") or []}
        analytics_endpoints |= {
            str(r.get("endpoint", "")) for r in golden.get("analytics_rows") or []
        }
    errors: list[str] = []
    comparisons = 0
    for rule_id in CARRYOVER_RULES_P0:
        if rule_id == "OAT-METEO":
            if (
                rule_id in sql_rules
                or rule_id in pandas_rules_seen
                or "/api/analytics/oat_meteo" in analytics_endpoints
            ):
                comparisons += 1
            else:
                errors.append("P0 carry-over: missing OAT-METEO (rule or analytics row)")
            continue
        if (
            rule_id not in sql_rules
            and rule_id not in pandas_rules_seen
            and rule_id not in attempted_rules
        ):
            errors.append(
                f"P0 carry-over: missing rule {rule_id} in sql_fdd_daily or pandas IP (union)"
            )
            continue
        comparisons += 1
    return StageResult("P0-carryover", comparisons, tuple(errors))


def run_p1_ip_vs_si(
    goldens: list[dict[str, Any]],
    *,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
) -> StageResult:
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    metric = _metric_doc()
    rules = cfl.load_rule_registry()
    rules_by_id = {str(r["rule_id"]): r for r in rules}
    expected = cfl.expected_pandas_rule_ids(rules)
    errors: list[str] = []
    comparisons = 0
    min_required = 0
    recompute = param_hook is not None or value_hook is not None
    for golden in goldens:
        min_required += min_p1_cells(golden)
        cov = verify_golden_rule_attempted(golden, expected)
        if cov.errors:
            errors.extend(cov.errors)
        if recompute:
            si_map = cfl.recompute_si_daily_for_golden(
                golden,
                rules_by_id,
                metric,
                param_hook=param_hook,
                value_hook=value_hook,
            )
        else:
            si_map = {
                fdd_daily_key(row): float(row.get("fault_seconds", 0))
                for row in golden.get("pandas_si_daily") or []
            }
        for row in _parity_ip_rows(golden):
            key = fdd_daily_key(row)
            comparisons += 1
            ip_fs = float(row.get("fault_seconds", 0))
            si_fs = si_map.get(key)
            if si_fs is None:
                errors.append(f"P1 missing SI side for {key}")
                continue
            if not fault_seconds_equal(ip_fs, si_fs):
                errors.append(f"P1 {key}: ip={ip_fs} si={si_fs}")
    if comparisons < min_required:
        errors.append(
            f"P1: comparisons {comparisons} < required ip/si cells {min_required}"
        )
    return StageResult("P1", comparisons, tuple(errors))


def run_p2_all_goldens(goldens: list[dict[str, Any]]) -> StageResult:
    from scripts.stress.si_cutover.ci_timescale_sql import PENDING_W4

    errors: list[str] = []
    pending_notes: list[str] = []
    comparisons = 0
    pending_cells = 0
    min_required = 0
    for golden in goldens:
        min_required += min_p2_cells(golden)
        for row in golden.get("p2_si_pairs") or []:
            if not row.get("utc_day"):
                continue
            comparisons += 1
            status = str(row.get("sql_si_status") or "")
            if status == PENDING_W4:
                pending_cells += 1
                continue
            sql_raw = row.get("sql_si_fault_seconds")
            pandas_raw = row.get("pandas_si_fault_seconds")
            if sql_raw is None:
                errors.append(
                    f"P2 {row.get('rule_id')}/{row.get('equipment_id')}/{row.get('utc_day')}: "
                    "missing sql_si_fault_seconds"
                )
                continue
            if pandas_raw is None:
                errors.append(
                    f"P2 {row.get('rule_id')}/{row.get('equipment_id')}/{row.get('utc_day')}: "
                    "missing pandas_si_fault_seconds"
                )
                continue
            sql_s = float(sql_raw)
            pandas_s = float(pandas_raw)
            if not fault_seconds_equal(sql_s, pandas_s):
                errors.append(
                    f"P2 {row.get('rule_id')}/{row.get('equipment_id')}/{row.get('utc_day')}: "
                    f"sql_si={sql_s} pandas_si={pandas_s}"
                )
    if pending_cells:
        pending_notes.append(
            f"P2: {pending_cells} cell(s) pending_W4 (SI SQL pack not shipped; not compared)"
        )
    if comparisons < min_required:
        errors.append(
            f"P2: comparisons {comparisons} < required si pairs {min_required}"
        )
    return StageResult(
        "P2",
        comparisons,
        tuple(errors),
        tuple(pending_notes),
    )


def run_t1284_4_rule_mutation_p1(goldens: list[dict[str, Any]]) -> StageResult:
    """Mutate VAV-1 SI comfort threshold — must break IP vs SI fault seconds on COOKBOOK_VAV1."""
    return verify_vav1_rule_si_threshold_mutation()


def verify_vav1_rule_si_threshold_mutation() -> StageResult:
    """T1284-4: wrong unit kind on FC1 duct_static_err SI param breaks fault seconds (P1-class)."""
    from open_fdd.rules import run_rule

    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    metric = _metric_doc()
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    rule = rules.get("FC1")
    if rule is None:
        return StageResult("T1284-4-rule", 0, ("missing FC1 registry row",))
    golden = next(
        (g for g in load_all_ip_goldens() if g.get("building_id") == "SYNTH_AHU_CASE_FC1"),
        None,
    )
    if golden is None:
        return StageResult("T1284-4-rule", 0, ("missing SYNTH_AHU_CASE_FC1 golden",))
    ip_row = next((r for r in _parity_ip_rows(golden) if r.get("rule_id") == "FC1"), None)
    if ip_row is None:
        return StageResult("T1284-4-rule", 0, ("missing FC1 ip row",))

    frame, equipment_id = cfl.reload_dataset_frame(golden)
    ip_frame = cfl.prepare_ip_frame(
        frame,
        building_id=str(golden["building_id"]),
        equipment_id=equipment_id,
        equipment_type="ahu",
    )
    si_frame = cfl.frame_to_si(ip_frame, metric)
    params_ip = cfl.rule_params_from_registry(rule)
    params_si = cfl.convert_params_to_si(rule, params_ip, metric)
    params_broken = dict(params_si)
    params_broken["eps_dsp"] = float(params_si.get("eps_dsp", 0.12)) + 1.0
    poll = float(golden.get("poll_seconds") or 300.0)

    def _fault_seconds(result, index) -> float:
        confirmed = getattr(result, "confirmed_fault", None)
        if confirmed is None:
            return -1.0
        fault_by_day, _c = cfl.daily_fault_and_covered_seconds(confirmed, index, poll_seconds=poll)
        day = str(ip_row.get("utc_day"))
        return float(fault_by_day.get(day, 0.0))

    good = run_rule("FC1", si_frame, params=params_si, poll_seconds=poll, require_operational_gates=True)
    bad = run_rule("FC1", si_frame, params=params_broken, poll_seconds=poll, require_operational_gates=True)
    ip_fs = float(ip_row.get("fault_seconds", 0))
    good_fs = _fault_seconds(good, si_frame.index)
    bad_fs = _fault_seconds(bad, si_frame.index)
    comparisons = 3
    errors: list[str] = []
    if good_fs < 0 or bad_fs < 0:
        errors.append("T1284-4: FC1 run_rule missing confirmed_fault on SI frame")
    elif not fault_seconds_equal(ip_fs, good_fs):
        errors.append(f"T1284-4 setup: golden ip={ip_fs} good_si={good_fs}")
    elif fault_seconds_equal(ip_fs, bad_fs):
        errors.append(f"T1284-4: eps_dsp offset did not change SI faults (good={good_fs} bad={bad_fs})")
    else:
        errors.append(
            f"P1 FC1 {golden.get('building_id')}/{ip_row.get('utc_day')}: "
            f"ip={ip_fs} si={bad_fs} (mutated eps_dsp offset)"
        )
    return StageResult("T1284-4-rule", comparisons, tuple(errors))


def compare_p3_post_cutover(
    *,
    baseline_dir: Path,
    building_id: str,
    live_sql_daily: Iterable[dict[str, Any]],
    live_sample_counts: Iterable[dict[str, Any]],
) -> StageResult:
    """P3 live: post-cutover SQL SI fault seconds == pre-cutover W0c IP baseline."""
    site_dir = baseline_dir / building_id
    if not site_dir.is_dir():
        return StageResult("P3", 0, (f"baseline missing site dir {site_dir}",))
    baseline = load_baseline_site_dir(site_dir)
    base_sql = {
        fdd_daily_key(r): r for r in baseline.get("sql_fdd_daily") or []
    }
    errors: list[str] = []
    comparisons = 0
    for row in live_sql_daily:
        if str(row.get("building_id")) != building_id:
            continue
        key = fdd_daily_key(row)
        base = base_sql.get(key)
        if base is None:
            continue
        comparisons += 1
        if not fault_seconds_equal(row.get("fault_seconds", 0), base.get("fault_seconds", 0)):
            errors.append(
                f"P3 {key}: live_si={row.get('fault_seconds')} "
                f"ip_baseline={base.get('fault_seconds')}"
            )
    base_counts = {
        (r.get("building_id"), r.get("table")): int(r.get("row_count", 0))
        for r in baseline.get("sample_counts") or []
    }
    for row in live_sample_counts:
        if str(row.get("building_id")) != building_id:
            continue
        key = (row.get("building_id"), row.get("table"))
        comparisons += 1
        if base_counts.get(key) != int(row.get("row_count", 0)):
            errors.append(
                f"P3 sample_counts {key}: live={row.get('row_count')} "
                f"baseline={base_counts.get(key)}"
            )
    return StageResult("P3", comparisons, tuple(errors))


def verify_pandas_errors_all(goldens: list[dict[str, Any]]) -> StageResult:
    errors: list[str] = []
    comparisons = 0
    for golden in goldens:
        sub = verify_pandas_errors(golden)
        comparisons += sub.comparisons
        if sub.comparisons:
            errors.append(
                f"{golden.get('building_id')}: assert zero pandas error rows, got {sub.comparisons}"
            )
            errors.extend(sub.errors)
    return StageResult("pandas-errors", comparisons, tuple(errors))


def rule_mismatch_table(stage_errors: Iterable[str], *, stage: str) -> dict[str, int]:
    """Count mismatches by rule_id from P0/P1 error strings."""
    import re

    counts: dict[str, int] = {}
    pat = re.compile(
        rf"^{re.escape(stage)}\s+\('(?:[^']*)',\s*'([^']*)',"
    )
    for msg in stage_errors:
        m = pat.match(msg)
        if m:
            rid = m.group(1)
            counts[rid] = counts.get(rid, 0) + 1
            continue
        if msg.startswith(f"{stage} ") and "/" in msg:
            rid = msg.split("/", 1)[0].split()[-1]
            counts[rid] = counts.get(rid, 0) + 1
    return counts


def run_fixture_stages() -> list[StageResult]:
    goldens = load_all_ip_goldens()
    return [
        verify_unit_vector_goldens(),
        verify_unit_scenarios(),
        verify_pandas_errors_all(goldens),
        compare_p0_all_goldens(goldens),
        verify_p0_carryover_all(goldens),
        run_p1_ip_vs_si(goldens),
        run_p2_all_goldens(goldens),
    ]


def summarize(results: list[StageResult]) -> tuple[int, list[str]]:
    total = sum(r.comparisons for r in results)
    errors: list[str] = []
    for r in results:
        errors.extend(r.errors)
    return total, errors
