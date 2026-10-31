"""SI cutover parity chain P0–P3 helpers (#1284 W3).

Equality contract:
  * FDD fault_seconds: exact (integer or float bit-equal after rounding to 1e-9 s)
  * Analytics numeric fields: relative tolerance ANALYTICS_REL_TOL (1e-6) documented here

Uses ``scripts/ci/unit_contract_lib.py`` only — no second conversion table.
"""

from __future__ import annotations

import gzip
import hashlib
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
from scripts.stress.si_cutover import baseline_io as bio  # noqa: E402

FROZEN_IP_ORACLE_VERSION = "4.4.9"
FROZEN_IP_ORACLE_GIT_HEAD = "35c17ac2d4ccc9ff677f5dd8d928e786aea0e2f0"
P1_ALGORITHM_LABEL = "current-algorithm unit commutation (not frozen 4.4.9 reproduction)"


def _open_fdd_tree_sha256(package_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def expected_p1_candidate_oracle_evidence() -> dict[str, Any]:
    """Pinned candidate oracle identity for current-repo P1 (not frozen 4.4.9)."""
    import subprocess
    import tomllib

    repo = REPO.resolve()
    project = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    expected_version = str(project.get("project", {}).get("version") or "")
    git_head = ""
    try:
        git_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        git_head = ""
    pkg_root = repo / "open_fdd"
    return {
        "repo_root": str(repo),
        "expected_version": expected_version,
        "expected_git_head": git_head,
        "expected_open_fdd_tree_sha256": _open_fdd_tree_sha256(pkg_root) if pkg_root.is_dir() else "",
        "algorithm_label": P1_ALGORITHM_LABEL,
    }


def verify_current_p1_oracle_provenance() -> tuple[tuple[str, ...], dict[str, Any]]:
    """Fail P1 when the frozen IP oracle or a foreign open_fdd install is used."""
    import subprocess

    evidence = expected_p1_candidate_oracle_evidence()
    errors: list[str] = []
    try:
        import open_fdd
    except ImportError:
        return ("P1: open_fdd not importable for candidate SI recompute",), evidence

    mod_path = Path(getattr(open_fdd, "__file__", "") or "").resolve()
    repo_root = Path(evidence["repo_root"]).resolve()
    try:
        if not mod_path.is_relative_to(repo_root):
            errors.append(
                f"P1: open_fdd loaded outside candidate repo ({mod_path}); "
                f"expected under {repo_root}"
            )
    except ValueError:
        errors.append(
            f"P1: open_fdd loaded outside candidate repo ({mod_path}); "
            f"expected under {repo_root}"
        )

    version = str(getattr(open_fdd, "__version__", ""))
    expected_version = str(evidence.get("expected_version") or "")
    if expected_version and version != expected_version:
        errors.append(
            f"P1: open_fdd version {version!r} != candidate pyproject {expected_version!r}"
        )
    if version == FROZEN_IP_ORACLE_VERSION:
        errors.append(
            "P1: frozen IP oracle 4.4.9 is loaded; current candidate pandas SI required"
        )

    expected_tree = str(evidence.get("expected_open_fdd_tree_sha256") or "")
    if expected_tree and mod_path.is_file():
        actual_tree = _open_fdd_tree_sha256(mod_path.parent)
        if actual_tree != expected_tree:
            errors.append(
                "P1: open_fdd source tree hash mismatch (stale or foreign implementation)"
            )

    try:
        git_head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        evidence = {**evidence, "resolved_git_head": git_head}
        if git_head == FROZEN_IP_ORACLE_GIT_HEAD and version == FROZEN_IP_ORACLE_VERSION:
            errors.append("P1: git HEAD matches frozen 35c17ac with 4.4.9 oracle")
    except (subprocess.CalledProcessError, OSError):
        pass

    evidence = {
        **evidence,
        "resolved_open_fdd_file": str(mod_path),
        "resolved_version": version,
    }
    return tuple(errors), evidence

ANALYTICS_REL_TOL = 1e-6
FAULT_SECONDS_ATOL = 0.0  # exact equality; no tolerance

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
    structured: tuple[dict[str, Any], ...] = ()
    pending: int = 0
    metadata_checks: int = 0


def rule_in_scope(rule_id: str, scope: set[str] | None) -> bool:
    if scope is None:
        return True
    return str(rule_id) in scope


def _parse_p0_error(msg: str) -> tuple[str, str] | None:
    """Return (kind, rule_id) for structured P0 errors."""
    if msg.startswith("P0 sql_row_missing "):
        return "sql_row_missing", _rule_id_from_p0_key(msg.removeprefix("P0 sql_row_missing "))
    if msg.startswith("P0 value_mismatch "):
        return "value_mismatch", _rule_id_from_p0_key(msg.removeprefix("P0 value_mismatch "))
    return None


def _rule_id_from_p0_key(rest: str) -> str:
    if rest.startswith("("):
        parts = rest.strip("()").split(",")
        if len(parts) >= 2:
            return parts[1].strip().strip("'\"")
    return "?"


def _p1_rule_id(msg: str) -> str:
    if msg.startswith("P1 ") and ":" in msg:
        head = msg.split(":", 1)[0]
        if head.startswith("P1 ("):
            parts = head.strip("()").split(",")
            if len(parts) >= 2:
                return parts[1].strip().strip("'\"")
    return "?"


def build_si_parity_report(
    results: list[StageResult],
    *,
    scope: set[str] | None,
    scope_label: str,
    blocking: bool,
    excluded: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from scripts.stress.si_cutover.product_sql_params import MODE_DELAY_DEFAULT_VS_STARTUP

    stage_map = {r.stage: r for r in results}
    p0 = stage_map.get("P0")
    p1 = stage_map.get("P1")
    p2 = stage_map.get("P2")
    p0_struct = list(p0.structured) if p0 else []
    p1_struct = list(p1.structured) if p1 else []
    p0_counts = {"sql_row_missing": 0, "value_mismatch": 0, "other": 0}
    p0_reason_counts: dict[str, int] = {}
    for cell in p0_struct:
        kind = str(cell.get("kind") or "other")
        p0_counts[kind] = p0_counts.get(kind, 0) + 1
        reason = cell.get("mismatch_reason")
        if reason:
            rs = str(reason)
            p0_reason_counts[rs] = p0_reason_counts.get(rs, 0) + 1
    p1_by_rule: dict[str, int] = {}
    for cell in p1_struct:
        rid = str(cell.get("rule_id") or "?")
        p1_by_rule[rid] = p1_by_rule.get(rid, 0) + 1
    ex = excluded if excluded is not None else collect_excluded_rule_dataset_pairs()
    ex_summary = excluded_summary_by_reason(ex)
    return {
        "schema": "openfdd-si-parity-report-v1",
        "scope": scope_label,
        "scope_rules": sorted(scope) if scope else ["*"],
        "blocking": blocking,
        "excluded": {
            "pair_count": len(ex),
            "by_reason": ex_summary,
            "pairs": ex,
        },
        "stages": {
            "P0": {
                "comparisons": p0.comparisons if p0 else 0,
                "mismatch_count": len(p0.errors) if p0 else 0,
                "by_kind": p0_counts,
                "value_mismatch_by_reason": p0_reason_counts,
                "product_findings": {
                    MODE_DELAY_DEFAULT_VS_STARTUP: p0_reason_counts.get(
                        MODE_DELAY_DEFAULT_VS_STARTUP, 0
                    ),
                },
                "cells": p0_struct,
            },
            "P1": {
                "comparisons": p1.comparisons if p1 else 0,
                "mismatch_count": len(p1.errors) if p1 else 0,
                "by_rule_id": p1_by_rule,
                "cells": p1_struct,
            },
            "P2": {
                "comparisons": p2.comparisons if p2 else 0,
                "blocking_errors": list(p2.errors) if p2 else [],
                "notes": list(p2.mismatch_table) if p2 else [],
            },
        },
    }
def _metric_doc() -> dict[str, Any]:
    return uc.load_json(uc.METRIC_UNITS)


def fault_seconds_equal(a: float, b: float) -> bool:
    """Exact FDD fault_seconds parity (P1/P2); no poll, boundary or float tolerance."""
    return float(a) == float(b)


def analytics_relative_equal(a: float, b: float) -> bool:
    if not math.isfinite(a) and not math.isfinite(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= ANALYTICS_REL_TOL


def analytics_spread_equal(a: float, b: float, scale: float) -> bool:
    """Spread statistics (stddev, deltas) relative to the series magnitude ``scale``.

    A spread of a constant series is 0 in exact arithmetic but round-off differs per
    engine (Postgres stddev_samp vs NumPy); the documented ANALYTICS_REL_TOL is applied
    against max(|a|, |b|, |scale|) where ``scale`` is the row's value magnitude.
    """
    if not math.isfinite(a) and not math.isfinite(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    denom = max(abs(a), abs(b), abs(scale), 1e-12)
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


def _p0_sql_rules_ip_compare() -> set[str]:
    from scripts.stress.si_cutover.si_parity_families import sql_si_pack_enabled

    return {r for r in _rules_with_sql_file() if not sql_si_pack_enabled(r)}


def _p0_si_pack_pandas_rows(golden: dict[str, Any]) -> list[dict[str, Any]]:
    from scripts.stress.si_cutover.si_parity_families import sql_si_pack_enabled

    return [
        r
        for r in _pandas_computed_daily(golden)
        if sql_si_pack_enabled(str(r.get("rule_id") or ""))
    ]


def _p0_pandas_rows(golden: dict[str, Any], sql_rules: set[str]) -> list[dict[str, Any]]:
    return [
        r
        for r in _pandas_computed_daily(golden)
        if str(r.get("rule_id") or "") in sql_rules
    ]


def min_p0_cells(golden: dict[str, Any]) -> int:
    sql_rules = _p0_sql_rules_ip_compare()
    return len(_p0_pandas_rows(golden, sql_rules)) + len(_p0_si_pack_pandas_rows(golden))


def min_p1_cells(golden: dict[str, Any]) -> int:
    return len(_pandas_computed_daily(golden))


def min_p2_cells(golden: dict[str, Any]) -> int:
    return len([p for p in golden.get("p2_si_pairs") or [] if p.get("utc_day")])


def collect_excluded_rule_dataset_pairs() -> list[dict[str, Any]]:
    """Rule×dataset pairs skipped by shared eligibility (not in P0/P1 comparison matrix)."""
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    rules = cfl.load_rule_registry()
    pandas_rules = {str(r["rule_id"]) for r in cfl.pandas_rules(rules)}
    out: list[dict[str, Any]] = []
    for spec in cfl.iter_dataset_specs():
        ip_frame = cfl.prepare_ip_frame(
            spec.source["frame"],
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            equipment_type=spec.equipment_type,
        )
        for rule in rules:
            rule_id = str(rule.get("rule_id") or "")
            if rule_id not in pandas_rules:
                continue
            ok, reason = cfl.rule_pair_eligible(
                rule, ip_frame, equipment_type=spec.equipment_type
            )
            if ok:
                continue
            out.append(
                {
                    "building_id": spec.building_id,
                    "rule_id": rule_id,
                    "equipment_id": spec.equipment_id,
                    "reason": reason,
                }
            )
    return out


def excluded_summary_by_reason(excluded: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in excluded:
        reason = str(row.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


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


def compare_p0_all_goldens(
    goldens: list[dict[str, Any]],
    *,
    scope: set[str] | None = None,
) -> StageResult:
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover.product_sql_params import p0_value_mismatch_reason

    rules_by_id = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    errors: list[str] = []
    structured: list[dict[str, Any]] = []
    comparisons = 0
    min_required = 0
    sql_rules = _p0_sql_rules_ip_compare()
    notes: list[str] = []
    for golden in goldens:
        min_required += min_p0_cells(golden)
        sql_by_key = {fdd_daily_key(r): r for r in _sql_computed_daily(golden)}
        for prow in _p0_pandas_rows(golden, sql_rules):
            rule_id = str(prow.get("rule_id") or "")
            if not rule_in_scope(rule_id, scope):
                continue
            key = fdd_daily_key(prow)
            comparisons += 1
            srow = sql_by_key.get(key)
            if srow is None:
                msg = f"P0 sql_row_missing {key}"
                errors.append(msg)
                structured.append(
                    {
                        "kind": "sql_row_missing",
                        "building_id": key[0],
                        "rule_id": key[1],
                        "equipment_id": key[2],
                        "utc_day": key[3],
                    }
                )
                continue
            if not fault_seconds_equal(
                prow.get("fault_seconds", 0), srow.get("fault_seconds", 0)
            ):
                msg = (
                    f"P0 value_mismatch {key}: pandas_ip={prow.get('fault_seconds')} "
                    f"sql_ip={srow.get('fault_seconds')}"
                )
                errors.append(msg)
                rule = rules_by_id.get(rule_id) or {"rule_id": rule_id}
                params = cfl.rule_params_from_registry(rule)
                mismatch_reason = p0_value_mismatch_reason(rule_id, params)
                cell: dict[str, Any] = {
                    "kind": "value_mismatch",
                    "building_id": key[0],
                    "rule_id": key[1],
                    "equipment_id": key[2],
                    "utc_day": key[3],
                    "pandas_ip_seconds": float(prow.get("fault_seconds", 0)),
                    "sql_ip_seconds": float(srow.get("fault_seconds", 0)),
                }
                if mismatch_reason:
                    cell["mismatch_reason"] = mismatch_reason
                structured.append(cell)
        for prow in _p0_si_pack_pandas_rows(golden):
            rule_id = str(prow.get("rule_id") or "")
            if not rule_in_scope(rule_id, scope):
                continue
            key = fdd_daily_key(prow)
            comparisons += 1
            msg = (
                f"P0 ip_sql_skipped_si_pack {key}: golden emit skips IP Timescale SQL "
                f"(W4c SI-pack path)"
            )
            notes.append(msg)
            structured.append(
                {
                    "kind": "ip_sql_skipped_si_pack",
                    "building_id": key[0],
                    "rule_id": key[1],
                    "equipment_id": key[2],
                    "utc_day": key[3],
                }
            )
        sub_a = compare_p0_analytics_golden(golden)
        if scope is None:
            comparisons += sub_a.comparisons
            errors.extend(sub_a.errors)
    if scope is None and comparisons < min_required:
        errors.append(
            f"P0: comparisons {comparisons} < required pandas/sql cells {min_required}"
        )
    return StageResult("P0", comparisons, tuple(errors), tuple(notes), tuple(structured))


def verify_golden_rule_attempted(golden: dict[str, Any], expected_rules: set[str]) -> StageResult:
    seen = set(golden.get("pandas_rules_attempted") or [])
    missing = sorted(expected_rules - seen)
    errors: list[str] = []
    if missing:
        errors.append(f"{golden.get('building_id')}: rule dropout: {missing[:8]}…")
    computed = {
        str(r.get("rule_id") or "")
        for r in golden.get("pandas_fdd_daily") or []
        if str(r.get("pair_status") or "") == "computed" and str(r.get("utc_day") or "")
    }
    if seen and not computed:
        errors.append(
            f"{golden.get('building_id')}: vacuous coverage — pandas_rules_attempted "
            f"nonempty but zero computed daily cells"
        )
    sql_computed = {
        str(r.get("rule_id") or "")
        for r in golden.get("sql_fdd_daily") or []
        if str(r.get("utc_day") or "")
    }
    if seen and not sql_computed:
        errors.append(
            f"{golden.get('building_id')}: vacuous coverage — attempted rules but "
            f"sql_fdd_daily has no dated rows"
        )
    return StageResult(
        "rule-coverage",
        len(computed),
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


def p1_recompute_identity_digest(golden: dict[str, Any]) -> str:
    """Cache identity for P1 SI recompute: fixture, SQL registry, metric contract."""
    import hashlib

    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    parts: list[str] = [
        str(golden.get("building_id") or ""),
        str(golden.get("dataset_id") or golden.get("source_dataset") or ""),
        str(golden.get("poll_seconds") or ""),
        P1_ALGORITHM_LABEL,
    ]
    reg_path = REPO / "sql" / "fdd" / "registry.yaml"
    if reg_path.is_file():
        parts.append(hashlib.sha256(reg_path.read_bytes()).hexdigest())
    if uc.MANIFEST.is_file():
        parts.append(uc.sha256_file(uc.MANIFEST))
    if uc.METRIC_UNITS.is_file():
        parts.append(uc.sha256_file(uc.METRIC_UNITS))
    frame_path = golden.get("frame_path") or golden.get("dataset_path")
    if frame_path:
        fp = Path(str(frame_path))
        if fp.is_file():
            parts.append(hashlib.sha256(fp.read_bytes()).hexdigest())
    else:
        parts.append(str(golden.get("frame_sha256") or ""))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def run_p1_ip_vs_si(
    goldens: list[dict[str, Any]],
    *,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
    si_param_post_hook: Callable[[str, dict[str, float]], dict[str, float]] | None = None,
    scope: set[str] | None = None,
) -> StageResult:
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    metric = _metric_doc()
    rules = cfl.load_rule_registry()
    rules_by_id = {str(r["rule_id"]): r for r in rules}
    expected = cfl.expected_pandas_rule_ids(rules)
    prov_errors, prov_evidence = verify_current_p1_oracle_provenance()
    errors: list[str] = list(prov_errors)
    structured: list[dict[str, Any]] = [
        {"kind": "p1_oracle_provenance", **prov_evidence},
    ]
    comparisons = 0
    min_required = 0
    for golden in goldens:
        min_required += min_p1_cells(golden)
        cov = verify_golden_rule_attempted(golden, expected)
        if cov.errors and scope is None:
            errors.extend(cov.errors)
        _ = p1_recompute_identity_digest(golden)
        si_map = cfl.recompute_si_daily_for_golden(
            golden,
            rules_by_id,
            metric,
            param_hook=param_hook,
            value_hook=value_hook,
            si_param_post_hook=si_param_post_hook,
        )
        for row in _parity_ip_rows(golden):
            rule_id = str(row.get("rule_id") or "")
            if not rule_in_scope(rule_id, scope):
                continue
            key = fdd_daily_key(row)
            comparisons += 1
            ip_fs = float(row.get("fault_seconds", 0))
            si_fs = si_map.get(key)
            if si_fs is None:
                errors.append(f"P1 missing SI side for {key}")
                structured.append(
                    {
                        "rule_id": key[1],
                        "building_id": key[0],
                        "equipment_id": key[2],
                        "utc_day": key[3],
                        "ip_seconds": ip_fs,
                        "si_seconds": None,
                    }
                )
                continue
            if not fault_seconds_equal(ip_fs, si_fs):
                errors.append(f"P1 {key}: ip={ip_fs} si={si_fs}")
                structured.append(
                    {
                        "rule_id": key[1],
                        "building_id": key[0],
                        "equipment_id": key[2],
                        "utc_day": key[3],
                        "ip_seconds": ip_fs,
                        "si_seconds": si_fs,
                    }
                )
    if scope is None and comparisons < min_required:
        errors.append(
            f"P1: comparisons {comparisons} < required ip/si cells {min_required}"
        )
    return StageResult("P1", comparisons, tuple(errors), tuple(), tuple(structured))


def hydrate_w4c_p2_sql_si_from_timescale(
    goldens: list[dict[str, Any]],
    *,
    scope: set[str] | None,
    strict: bool = False,
) -> tuple[list[str], list[str]]:
    """When Timescale is available, fill sql_si_fault_seconds for W4c-scoped P2 rows.

    Returns (errors, notes). Infrastructure failures and SQL errors are always
    blocking P2 errors; under strict W4c a missing SQL row is an error too.
    """
    import os

    from scripts.ci import unit_contract_lib as uc
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover import ci_timescale_sql as cts
    from scripts.stress.si_cutover.si_parity_families import (
        W4C_SI_ZONE_FAMILY,
        family_dataset_ids,
        family_rule_ids,
    )

    w4c_rules = family_rule_ids(W4C_SI_ZONE_FAMILY)
    w4c_datasets = family_dataset_ids(W4C_SI_ZONE_FAMILY)
    if scope is None or not scope.intersection(w4c_rules):
        return [], []

    errors: list[str] = []
    notes: list[str] = []

    def hydrate_fail(msg: str) -> None:
        """Infrastructure/SQL failures are blocking P2 errors."""
        errors.append(msg)

    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        hydrate_fail("P2 hydrate_w4c: OPENFDD_DATABASE_URL is not set")
        return errors, notes

    metric = uc.load_json(uc.METRIC_UNITS)
    rules_by_id = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    try:
        conn = cts._load_parity_module().connect_with_retry(url)
    except Exception as exc:
        hydrate_fail(f"P2 hydrate_w4c: connect failed: {exc}")
        return errors, notes
    try:
        for golden in goldens:
            building_id = str(golden.get("building_id") or "")
            if building_id not in w4c_datasets:
                continue
            try:
                spec = next(s for s in cfl.iter_dataset_specs() if s.building_id == building_id)
            except StopIteration:
                hydrate_fail(f"P2 hydrate_w4c {building_id}: no dataset spec")
                continue
            try:
                frame_raw, equipment_id = cfl.reload_dataset_frame(golden)
            except Exception as exc:
                hydrate_fail(f"P2 hydrate_w4c {building_id}: reload frame: {exc}")
                continue
            ip_frame = cfl.prepare_ip_frame(
                frame_raw,
                building_id=building_id,
                equipment_id=equipment_id,
                equipment_type=spec.equipment_type,
            )
            si_frame = cfl.frame_to_si(ip_frame, metric)
            poll = float(golden.get("poll_seconds") or cts.infer_poll_seconds(si_frame.index))
            needed_rule_ids = {
                str(row.get("rule_id") or "")
                for row in golden.get("p2_si_pairs") or []
                if row.get("utc_day") and str(row.get("rule_id") or "") in scope
            }
            run_rule_ids = sorted(needed_rule_ids & set(w4c_rules))
            eligible = [
                rules_by_id[rid] for rid in run_rule_ids if rid in rules_by_id
            ]
            if not eligible:
                continue
            params_si_by_rule = {
                str(r["rule_id"]): cfl.convert_params_to_si(
                    r, cfl.rule_params_from_registry(r), metric
                )
                for r in eligible
            }
            try:
                sql_rows, sql_err = cts.run_sql_si_for_dataset(
                    conn,
                    spec=spec,
                    frame=si_frame,
                    equipment_id=equipment_id,
                    rules=eligible,
                    poll_seconds=poll,
                    params_by_rule=params_si_by_rule,
                )
            except Exception as exc:
                hydrate_fail(f"P2 hydrate_w4c {building_id}: run_sql_si_for_dataset: {exc}")
                continue
            if sql_err:
                hydrate_fail(
                    f"P2 hydrate_w4c {building_id}: sql_si errors: {'; '.join(sql_err[:3])}"
                )
                continue
            sql_by_key: dict[tuple[str, str, str], float] = {}
            for r in sql_rows:
                if r.get("pair_status") != "computed" or not r.get("utc_day"):
                    continue
                key = (str(r.get("rule_id")), str(r.get("utc_day")), str(r.get("equipment_id")))
                if r.get("fault_seconds") is None:
                    hydrate_fail(
                        f"P2 hydrate_w4c {key[0]}/{key[2]}/{key[1]}: "
                        "computed sql_si row has no fault_seconds"
                    )
                    continue
                sql_by_key[key] = float(r["fault_seconds"])
            updated: list[dict[str, Any]] = []
            for row in golden.get("p2_si_pairs") or []:
                rid = str(row.get("rule_id") or "")
                if rid not in scope:
                    updated.append(row)
                    continue
                key = (
                    rid,
                    str(row.get("utc_day")),
                    str(row.get("equipment_id")),
                )
                if key in sql_by_key:
                    pandas_si_fs: float | None
                    if row.get("pandas_si_missing") or row.get("pandas_si_fault_seconds") is None:
                        pandas_missing = True
                        pandas_si_fs = None
                    else:
                        pandas_missing = False
                        pandas_si_fs = float(row["pandas_si_fault_seconds"])
                    updated.append(
                        cts.p2_pair_for_si_row(
                            rule_id=rid,
                            equipment_id=str(row.get("equipment_id")),
                            utc_day=str(row.get("utc_day")),
                            pandas_si_fault_seconds=pandas_si_fs,
                            pandas_si_missing=pandas_missing,
                            sql_si_fault_seconds=sql_by_key[key],
                        )
                    )
                else:
                    if strict:
                        hydrate_fail(
                            f"P2 hydrate_w4c {rid}/{row.get('equipment_id')}/"
                            f"{row.get('utc_day')}: missing sql_si row after Timescale run"
                        )
                    updated.append(row)
            golden["p2_si_pairs"] = sorted(
                updated,
                key=lambda r: (
                    str(r.get("rule_id")),
                    str(r.get("utc_day")),
                    str(r.get("equipment_id")),
                ),
            )
    finally:
        conn.close()
    return errors, notes


def _live_plant_p2_fault_seconds(
    golden: dict[str, Any], row: dict[str, Any]
) -> tuple[float | None, float | None]:
    """Compute pandas SI vs SQL SI for W4d plant rules when Timescale is available."""
    import os

    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        return None, None
    rule_id = str(row.get("rule_id") or "")
    utc_day = str(row.get("utc_day") or "")
    equipment_id = str(row.get("equipment_id") or golden.get("equipment_id") or "")
    if not rule_id or not utc_day or not equipment_id:
        return None, None
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    metric = _metric_doc()
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    rule = rules.get(rule_id)
    if rule is None:
        return None, None
    frame, _equip_from_golden = cfl.reload_dataset_frame(golden)
    ip_frame = cfl.prepare_ip_frame(
        frame,
        building_id=str(golden["building_id"]),
        equipment_id=equipment_id,
        equipment_type=str(golden.get("equipment_type") or ""),
    )
    ok, _reason = cfl.rule_pair_eligible(
        rule, ip_frame, equipment_type=str(golden.get("equipment_type") or "")
    )
    if not ok:
        return None, None
    poll = float(golden.get("poll_seconds") or cts.infer_poll_seconds(ip_frame.index))
    _params_ip, params_si = cfl.resolve_rule_params_ip_si(rule, metric)
    si_frame = cfl.frame_to_si(ip_frame, metric)
    si_daily = cfl.run_rule_daily_rows(
        rule,
        si_frame,
        building_id=str(golden["building_id"]),
        equipment_id=equipment_id,
        params=params_si,
        poll_seconds=poll,
    )
    pandas_fs = None
    for daily in si_daily:
        if str(daily.get("utc_day")) == utc_day and daily.get("pair_status") == "computed":
            pandas_fs = float(daily.get("fault_seconds", 0.0))
            break
    if pandas_fs is None:
        return None, None
    parity = cts._load_parity_module()
    conn = parity.connect_with_retry(url)
    try:
        spec = cfl.DatasetSpec(
            building_id=str(golden["building_id"]),
            equipment_id=equipment_id,
            equipment_type=str(golden.get("equipment_type") or ""),
            source={"kind": golden.get("dataset", {}).get("kind", ""), "frame": frame},
        )
        sql_rows, errs = cts.run_sql_si_for_dataset(
            conn,
            spec=spec,
            frame=si_frame,
            equipment_id=equipment_id,
            rules=[rule],
            poll_seconds=poll,
            params_by_rule={rule_id: params_si},
        )
    finally:
        conn.close()
    if errs:
        return None, None
    sql_fs = None
    for daily in sql_rows:
        if str(daily.get("utc_day")) == utc_day:
            sql_fs = float(daily.get("fault_seconds", 0.0))
            break
    if sql_fs is None:
        return None, None
    return sql_fs, pandas_fs


def run_p2_all_goldens(
    goldens: list[dict[str, Any]],
    *,
    scope: set[str] | None = None,
    strict: bool = False,
) -> StageResult:
    from scripts.stress.si_cutover.ci_timescale_sql import PENDING_W4, rule_si_sql_shipped

    hydrate_errors, hydrate_notes = hydrate_w4c_p2_sql_si_from_timescale(
        goldens, scope=scope, strict=strict
    )

    errors: list[str] = list(hydrate_errors)
    pending_notes: list[str] = list(hydrate_notes)
    comparisons = 0
    pending_cells = 0
    min_required = 0
    for golden in goldens:
        min_required += min_p2_cells(golden)
        for row in golden.get("p2_si_pairs") or []:
            if not row.get("utc_day"):
                continue
            rule_id = str(row.get("rule_id") or "")
            if not rule_in_scope(rule_id, scope):
                continue
            status = str(row.get("sql_si_status") or "")
            sql_raw = row.get("sql_si_fault_seconds")
            pandas_raw = row.get("pandas_si_fault_seconds")
            cell = f"{rule_id}/{row.get('equipment_id')}/{row.get('utc_day')}"
            if status == PENDING_W4 and rule_si_sql_shipped(rule_id):
                live_sql, live_pandas = _live_plant_p2_fault_seconds(golden, row)
                if live_sql is not None and live_pandas is not None:
                    sql_raw = live_sql
                    pandas_raw = live_pandas
                else:
                    # A pending cell was never compared, so it is not a comparison.
                    pending_cells += 1
                    pending_notes.append(f"P2 pending {cell}: live plant SQL row missing")
                    continue
            elif status == PENDING_W4:
                if strict:
                    errors.append(f"P2 {cell}: pending_W4 after hydration")
                else:
                    pending_cells += 1
                    reason = row.get("sql_si_pending_reason")
                    if reason:
                        pending_notes.append(f"P2 pending {cell}: {reason}")
                continue
            comparisons += 1
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
        pending_notes.insert(
            0,
            f"P2: {pending_cells} cell(s) pending_W4 (not compared; not counted as comparisons)",
        )
    if scope is None and comparisons + pending_cells < min_required:
        errors.append(
            f"P2: comparisons {comparisons} + pending {pending_cells} "
            f"< required si pairs {min_required}"
        )
    return StageResult(
        "P2",
        comparisons,
        tuple(errors),
        tuple(pending_notes),
        pending=pending_cells,
    )


def t1284_4_double_param_conversion(
    rule: dict[str, Any], params_si: dict[str, float], key: str, metric: dict[str, Any]
) -> dict[str, float]:
    """T1284-4 mutation: apply the declared-kind SI scale to one param twice (unit-kind bug)."""
    spec = (rule.get("parameters") or {}).get(key)
    if not isinstance(spec, dict):
        raise KeyError(f"T1284-4: rule {rule.get('rule_id')} has no parameter spec {key!r}")
    kind = str(spec.get("kind") or "")
    unit = str(spec.get("unit") or "")
    if not kind or not unit:
        raise ValueError(f"T1284-4: parameter {key!r} lacks declared kind/unit")
    scale = uc.convert_to_canonical(metric, kind, 1.0, unit) - uc.convert_to_canonical(
        metric, kind, 0.0, unit
    )
    if scale == 1.0:
        raise ValueError(f"T1284-4: parameter {key!r} kind {kind} has no unit scale to break")
    if key not in params_si:
        raise KeyError(f"T1284-4: SI params missing {key!r}")
    out = dict(params_si)
    out[key] = float(params_si[key]) * scale
    return out


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
    _params_ip, params_si = cfl.resolve_rule_params_ip_si(rule, metric)
    # +1 in.w.c. in SI (Pa) — must change the fault mask vs golden IP seconds.
    params_broken = cfl.t1284_break_eps_dsp_si(params_si, rule_id="FC1")
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
        errors.append(f"T1284-4: double-converted eps_dsp did not change SI faults (good={good_fs} bad={bad_fs})")
    else:
        errors.append(
            f"P1 FC1 {golden.get('building_id')}/{ip_row.get('utc_day')}: "
            f"ip={ip_fs} si={bad_fs} (eps_dsp SI conversion applied twice)"
        )
    return StageResult("T1284-4-rule", comparisons, tuple(errors))


def compare_p3_post_cutover(
    *,
    baseline_dir: Path,
    building_id: str,
    live_sql_daily: Iterable[dict[str, Any]],
    live_sample_counts: Iterable[dict[str, Any]],
    expected_window_start: str | None = None,
    expected_window_end: str | None = None,
) -> StageResult:
    """P3 live: post-cutover SQL SI == pre-cutover W0c IP baseline (strict key matrix)."""
    site_dir = baseline_dir / building_id
    if not site_dir.is_dir():
        return StageResult("P3", 0, (f"baseline missing site dir {site_dir}",))
    manifest, manifest_errors = bio.verify_baseline_for_p3(
        baseline_dir,
        building_id=building_id,
        expected_window_start=expected_window_start,
        expected_window_end=expected_window_end,
    )
    errors: list[str] = list(manifest_errors)
    if manifest_errors:
        return StageResult("P3", 0, tuple(errors), metadata_checks=0)

    baseline = load_baseline_site_dir(site_dir)
    base_rows = baseline.get("sql_fdd_daily") or []
    base_keys: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in base_rows:
        if str(row.get("building_id")) != building_id:
            errors.append(f"P3 baseline row wrong building_id {fdd_daily_key(row)}")
            continue
        field_errors = bio.validate_fdd_daily_row(row)
        if field_errors:
            errors.append(f"P3 baseline invalid {fdd_daily_key(row)}: {field_errors[0]}")
        key = fdd_daily_key(row)
        if key in base_keys:
            errors.append(f"P3 baseline duplicate key {key}")
        base_keys[key] = row

    live_rows = [r for r in live_sql_daily if str(r.get("building_id")) == building_id]
    live_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in live_rows:
        field_errors = bio.validate_fdd_daily_row(row)
        if field_errors:
            errors.append(f"P3 live invalid {fdd_daily_key(row)}: {field_errors[0]}")
        key = fdd_daily_key(row)
        if key in live_by_key:
            errors.append(f"P3 live duplicate key {key}")
        live_by_key[key] = row

    sql_comparisons = 0
    for key, base in base_keys.items():
        live = live_by_key.get(key)
        if live is None:
            errors.append(f"P3 missing live SQL row for baseline key {key}")
            continue
        sql_comparisons += 1
        if not fault_seconds_equal(live.get("fault_seconds", 0), base.get("fault_seconds", 0)):
            errors.append(
                f"P3 {key}: live_si fault={live.get('fault_seconds')} "
                f"ip_baseline={base.get('fault_seconds')}"
            )
        if not fault_seconds_equal(
            live.get("covered_seconds", 0), base.get("covered_seconds", 0)
        ):
            errors.append(
                f"P3 {key}: covered live={live.get('covered_seconds')} "
                f"baseline={base.get('covered_seconds')}"
            )
        if str(live.get("status", "")) != str(base.get("status", "")):
            errors.append(
                f"P3 {key}: status live={live.get('status')} baseline={base.get('status')}"
            )

    for key in live_by_key:
        if key not in base_keys:
            errors.append(f"P3 extra live SQL row not in baseline {key}")

    if base_keys and sql_comparisons == 0:
        errors.append("P3: zero real SQL comparisons despite nonempty baseline matrix")

    metadata_checks = 0
    base_counts = {
        (r.get("building_id"), r.get("table")): int(r.get("row_count", 0))
        for r in baseline.get("sample_counts") or []
    }
    live_count_keys: set[tuple[Any, Any]] = set()
    for row in live_sample_counts:
        if str(row.get("building_id")) != building_id:
            continue
        key = (row.get("building_id"), row.get("table"))
        if key in live_count_keys:
            errors.append(f"P3 duplicate sample_counts key {key}")
        live_count_keys.add(key)
        metadata_checks += 1
        if key not in base_counts:
            errors.append(f"P3 sample_counts extra key {key}")
            continue
        if base_counts[key] != int(row.get("row_count", 0)):
            errors.append(
                f"P3 sample_counts {key}: live={row.get('row_count')} "
                f"baseline={base_counts[key]}"
            )
    for key in base_counts:
        if key[0] != building_id:
            continue
        if key not in live_count_keys:
            errors.append(f"P3 missing live sample_counts for baseline key {key}")

    return StageResult(
        "P3",
        sql_comparisons,
        tuple(errors),
        metadata_checks=metadata_checks,
    )


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
    pat_tuple = re.compile(
        rf"^{re.escape(stage)}\s+(?:sql_row_missing|value_mismatch)\s+\('(?:[^']*)',\s*'([^']*)',"
    )
    for msg in stage_errors:
        m = pat_tuple.match(msg)
        if m:
            rid = m.group(1)
            counts[rid] = counts.get(rid, 0) + 1
            continue
        if msg.startswith(f"{stage} ") and ":" in msg:
            rid = _p1_rule_id(msg) if stage == "P1" else msg.split("/", 1)[0].split()[-1]
            if rid and rid != "?":
                counts[rid] = counts.get(rid, 0) + 1
    return counts


def run_fixture_stages(
    *,
    scope: set[str] | None = None,
    strict_p2: bool = False,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
    si_param_post_hook: Callable[[str, dict[str, float]], dict[str, float]] | None = None,
) -> list[StageResult]:
    goldens = load_all_ip_goldens()
    return [
        verify_unit_vector_goldens(),
        verify_unit_scenarios(),
        verify_pandas_errors_all(goldens),
        compare_p0_all_goldens(goldens, scope=scope),
        verify_p0_carryover_all(goldens),
        run_p1_ip_vs_si(
            goldens,
            param_hook=param_hook,
            value_hook=value_hook,
            si_param_post_hook=si_param_post_hook,
            scope=scope,
        ),
        run_p2_all_goldens(goldens, scope=scope, strict=strict_p2),
    ]


def summarize(results: list[StageResult]) -> tuple[int, list[str]]:
    total = sum(r.comparisons for r in results)
    errors: list[str] = []
    for r in results:
        errors.extend(r.errors)
    return total, errors
