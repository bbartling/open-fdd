"""SQL-QUAL-06 rule × tuner matrix: actual runner C/D invocations (harness only)."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3a import runner_identities as rid  # noqa: E402
from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402
from scripts.stress.si_cutover import ci_timescale_sql as cts  # noqa: E402

DB_DATASET_BUILDINGS = frozenset(
    {
        "COOKBOOK_FC1",
        "COOKBOOK_FC2",
        "COOKBOOK_VAV1",
    }
)

# Cookbook fixtures can exercise these rules with meaningful pandas/SQL daily rows.
MATRIX_EXEC_RULE_IDS = frozenset(
    {
        "FC1",
        "FC2",
        "FC3",
        "VAV-1",
        "VAV-2",
        "ECON-4",
        "SV-RANGE",
        "SV-FLATLINE",
        "SV-SPIKE",
        "SV-STALE",
        "PID-HUNT-1",
        "FC15",
        "AHU-DUCTHI",
        "CMD-1",
        "OA-1",
        "TRIM-1",
        "SCHED-247",
    }
)

FROZEN_AB_PREREQ = (
    "frozen runners A (4.4.9 pandas IP) and B (35c17ac product SQL) require a dedicated "
    "pinned oracle checkout and old SQL execution path; identity dictionaries alone are not executions"
)

LEDGER_PATH = Path(__file__).resolve().parent / "expected_change_ledger.json"

CD_SUBSET_SCOPE_NOTE = (
    "Cookbook C/D subset: rules in MATRIX_EXEC_RULE_IDS on COOKBOOK_FC1/FC2/VAV1 only; "
    "full SQL-QUAL-06 / A–D qualification requires frozen A/B executions and complete rule families"
)


def _load_expected_change_ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


@dataclass
class DailyCompareResult:
    compared_cells: int = 0
    numeric_mismatch: int = 0
    shape_mismatch: int = 0
    duplicate_keys: int = 0

    @property
    def total_mismatch(self) -> int:
        return self.numeric_mismatch + self.shape_mismatch + self.duplicate_keys


@dataclass
class CaseCompareResult:
    daily: DailyCompareResult
    both_empty: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def meaningfully_compared(self) -> bool:
        return self.daily.compared_cells > 0 and not self.errors

    @property
    def case_pass(self) -> bool:
        if self.errors:
            return False
        if self.both_empty:
            return False
        return self.daily.total_mismatch == 0 and self.daily.compared_cells > 0


@dataclass
class MatrixRow:
    rule_id: str
    tuner: str | None
    tuner_effect: str
    required: int = 0
    attempted: int = 0
    cases_compared: int = 0
    compared_cells: int = 0
    numeric_mismatch: int = 0
    shape_mismatch: int = 0
    case_failures: int = 0
    case_insufficient: int = 0
    skipped: int = 0
    unsupported: int = 0
    runner_a: str = "BLOCKED"
    runner_b: str = "BLOCKED"
    runner_c: str = "PENDING"
    runner_d: str = "PENDING"
    status: str = "PENDING"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "tuner": self.tuner,
            "tuner_effect": self.tuner_effect,
            "required": self.required,
            "attempted": self.attempted,
            "cases_compared": self.cases_compared,
            "compared_cells": self.compared_cells,
            "numeric_mismatch": self.numeric_mismatch,
            "shape_mismatch": self.shape_mismatch,
            "case_failures": self.case_failures,
            "case_insufficient": self.case_insufficient,
            "skipped": self.skipped,
            "unsupported": self.unsupported,
            "runner_a": self.runner_a,
            "runner_b": self.runner_b,
            "runner_c": self.runner_c,
            "runner_d": self.runner_d,
            "status": self.status,
            "detail": self.detail,
        }


def _git_has_commit(sha: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "-t", sha],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "commit"


def _frozen_ab_blocked() -> tuple[str, str]:
    if _git_has_commit(rid.RUNNER_A_GIT_HEAD):
        return "BLOCKED", FROZEN_AB_PREREQ
    return "BLOCKED", f"{FROZEN_AB_PREREQ}; missing git object {rid.RUNNER_A_GIT_HEAD}"


def tuner_value_cases(pspec: dict[str, Any] | None) -> list[tuple[str, float | None]]:
    """Default, min, max, nondefault, and boundary values for a catalog parameter."""
    if not pspec:
        return [("default", None)]
    default = float(pspec.get("default", 0.0))
    mn = float(pspec.get("min", default))
    mx = float(pspec.get("max", default))
    step = float(pspec.get("step") or 1.0)
    cases: list[tuple[str, float | None]] = [
        ("default", default),
        ("min", mn),
        ("max", mx),
    ]
    nondefault: float | None = None
    for candidate in (mn + (mx - mn) / 2.0, default + step, default - step, mx - step, mn + step):
        if mn <= candidate <= mx and abs(candidate - default) > 1e-9:
            nondefault = candidate
            break
    if nondefault is not None:
        cases.append(("nondefault", nondefault))
    boundary = mn if abs(default - mn) > 1e-9 else mx
    if all(label != "boundary" for label, _ in cases):
        cases.append(("boundary", boundary))
    # De-dupe values while preserving first label.
    seen: set[float | None] = set()
    out: list[tuple[str, float | None]] = []
    for label, val in cases:
        key = None if val is None else round(float(val), 12)
        if key in seen:
            continue
        seen.add(key)
        out.append((label, val))
    return out


def _daily_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("building_id") or ""),
        str(row.get("rule_id") or ""),
        str(row.get("equipment_id") or ""),
        str(row.get("utc_day") or ""),
    )


def _daily_rows_computed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r for r in rows if r.get("utc_day") and str(r.get("pair_status") or "") == "computed"
    ]


def _daily_map_with_duplicates(
    rows: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], list[tuple[str, str, str, str]]]:
    out: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    dupes: list[tuple[str, str, str, str]] = []
    for row in rows:
        key = _daily_key(row)
        if key in out:
            dupes.append(key)
        out[key] = row
    return out, dupes


def _coverage_equal(pd_row: dict[str, Any], sql_row: dict[str, Any]) -> bool:
    pd_cov = pd_row.get("covered_seconds")
    sql_cov = sql_row.get("covered_seconds")
    if pd_cov is None and sql_cov is None:
        return True
    if pd_cov is None or sql_cov is None:
        return False
    return float(pd_cov) == float(sql_cov)


def _compare_daily(
    pandas_rows: list[dict[str, Any]], sql_rows: list[dict[str, Any]]
) -> DailyCompareResult:
    pd_daily = _daily_rows_computed(pandas_rows)
    sql_daily = _daily_rows_computed(sql_rows)
    pd_map, pd_dupes = _daily_map_with_duplicates(pd_daily)
    sql_map, sql_dupes = _daily_map_with_duplicates(sql_daily)
    result = DailyCompareResult(
        duplicate_keys=len(set(pd_dupes)) + len(set(sql_dupes)),
    )
    if result.duplicate_keys:
        result.shape_mismatch += result.duplicate_keys
    all_keys = set(pd_map) | set(sql_map)
    for key in sorted(all_keys, key=repr):
        pd_row = pd_map.get(key)
        sql_row = sql_map.get(key)
        if pd_row is None or sql_row is None:
            result.shape_mismatch += 1
            continue
        result.compared_cells += 1
        if not cts.pc_fault_seconds_equal(
            float(pd_row.get("fault_seconds", 0)), float(sql_row.get("fault_seconds", 0))
        ):
            result.numeric_mismatch += 1
            continue
        if not _coverage_equal(pd_row, sql_row):
            result.numeric_mismatch += 1
    return result


def _dataset_specs() -> list[cfl.DatasetSpec]:
    return [s for s in cfl.iter_dataset_specs() if s.building_id in DB_DATASET_BUILDINGS]


def _si_context(spec: cfl.DatasetSpec, metric: dict[str, Any]):
    frame_raw = spec.source["frame"]
    equipment_id = spec.equipment_id
    ip_frame = cfl.prepare_ip_frame(
        frame_raw,
        building_id=spec.building_id,
        equipment_id=equipment_id,
        equipment_type=spec.equipment_type,
    )
    si_frame = cfl.frame_to_si(ip_frame, metric)
    poll = float(cts.infer_poll_seconds(si_frame.index))
    return ip_frame, si_frame, equipment_id, poll


def _registry_param_for_catalog_tuner(
    rule: dict[str, Any], catalog_tuner: str | None
) -> tuple[str | None, str | None]:
    """Resolve catalog tuner key to a registry parameter name (or error)."""
    if not catalog_tuner:
        return None, None
    rule_id = str(rule.get("rule_id") or "")
    params = rule.get("parameters") or {}
    if catalog_tuner in params:
        return catalog_tuner, None
    if catalog_tuner == "confirm_min" and "confirm_seconds" in params:
        return "confirm_seconds", None
    return None, f"{rule_id}/{catalog_tuner}: tuner not declared in registry parameters"


def _params_si_for_case(
    rule: dict[str, Any],
    metric: dict[str, Any],
    *,
    tuner_name: str | None,
    tuner_value: float | None,
) -> dict[str, float]:
    registry_tuner, _err = _registry_param_for_catalog_tuner(rule, tuner_name)

    def param_hook(name: str, val: float) -> float:
        if registry_tuner is not None and name == registry_tuner and tuner_value is not None:
            hooked = float(tuner_value)
            if tuner_name == "confirm_min" and registry_tuner == "confirm_seconds":
                hooked *= 60.0
            return hooked
        return val

    _params_ip, params_si = cfl.resolve_rule_params_ip_si(rule, metric, param_hook=param_hook)
    return params_si


def _execute_cd_case(
    conn,
    spec: cfl.DatasetSpec,
    rule: dict[str, Any],
    *,
    si_frame,
    equipment_id: str,
    poll: float,
    tuner_name: str | None,
    tuner_value: float | None,
    metric: dict[str, Any],
) -> CaseCompareResult:
    from open_fdd.rules import RULES_BY_ID  # noqa: PLC0415

    rule_id = str(rule.get("rule_id") or "")
    params_si = _params_si_for_case(
        rule, metric, tuner_name=tuner_name, tuner_value=tuner_value
    )
    if not rule.get("pandas_function") and rule_id not in RULES_BY_ID:
        return CaseCompareResult(
            daily=DailyCompareResult(),
            errors=[f"{spec.building_id}/{rule_id}: no pandas twin"],
        )

    pandas_rows = cfl.run_rule_daily_rows(
        rule,
        si_frame,
        building_id=spec.building_id,
        equipment_id=equipment_id,
        params=params_si,
        poll_seconds=poll,
    )
    try:
        sql_rows, sql_errs = cts.run_sql_si_for_dataset(
            conn,
            spec=spec,
            frame=si_frame,
            equipment_id=equipment_id,
            rules=[rule],
            poll_seconds=poll,
            params_by_rule={rule_id: params_si},
        )
    except Exception as exc:
        detail = str(exc)
        try:
            conn.rollback()
        except Exception as rollback_exc:
            detail = f"{exc}; rollback failed: {rollback_exc}"
        return CaseCompareResult(
            daily=DailyCompareResult(),
            errors=[f"{spec.building_id}/{rule_id}: {detail}"],
        )

    if sql_errs:
        try:
            conn.rollback()
        except Exception as rollback_exc:
            return CaseCompareResult(
                daily=DailyCompareResult(),
                errors=[
                    f"{spec.building_id}/{rule_id}: {sql_errs[0]}; rollback failed: {rollback_exc}"
                ],
            )
        return CaseCompareResult(
            daily=DailyCompareResult(),
            errors=[f"{spec.building_id}/{rule_id}: {sql_errs[0]}"],
        )

    pd_daily = _daily_rows_computed(pandas_rows)
    sql_daily = _daily_rows_computed(sql_rows)
    daily = _compare_daily(pandas_rows, sql_rows)
    both_empty = not pd_daily and not sql_daily
    if both_empty:
        return CaseCompareResult(daily=daily, both_empty=True, errors=[])
    return CaseCompareResult(daily=daily, both_empty=False, errors=[])


def build_matrix_rows() -> list[MatrixRow]:
    catalog = json.loads((REPO / "sql" / "fdd" / "tuning_catalog.json").read_text(encoding="utf-8"))
    registry = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    pandas_rules = {str(r["rule_id"]) for r in cfl.pandas_rules(cfl.load_rule_registry())}
    runner_a, runner_b = _frozen_ab_blocked()
    rows: list[MatrixRow] = []
    for entry in catalog.get("rules") or []:
        rid_key = str(entry.get("rule_id") or "")
        if rid_key not in registry or rid_key not in pandas_rules:
            continue
        params = entry.get("parameters") or {}
        if not params:
            rows.append(
                MatrixRow(
                    rule_id=rid_key,
                    tuner=None,
                    tuner_effect="",
                    runner_a=runner_a,
                    runner_b=runner_b,
                    detail=runner_b,
                )
            )
            continue
        for pname, pspec in params.items():
            effect = str(pspec.get("effect") or "")
            rows.append(
                MatrixRow(
                    rule_id=rid_key,
                    tuner=str(pname),
                    tuner_effect=effect,
                    runner_a=runner_a,
                    runner_b=runner_b,
                    detail=runner_b,
                )
            )
    return rows


def _row_terminal_status(row: MatrixRow) -> str:
    if row.numeric_mismatch or row.shape_mismatch or row.case_failures:
        return "FAIL"
    if row.required == 0:
        return "SKIPPED"
    if row.cases_compared < row.required:
        return "INCOMPLETE"
    if row.case_insufficient:
        return "INCOMPLETE"
    if row.cases_compared == row.required and row.required > 0:
        return "PASS"
    return "INCOMPLETE"


def _aggregate_matrix_status(rows: list[MatrixRow], *, cells_compared: int) -> str:
    if cells_compared == 0:
        return "INCOMPLETE"
    for row in rows:
        if row.rule_id not in MATRIX_EXEC_RULE_IDS:
            continue
        if row.tuner_effect == "unsupported" or row.rule_id == "SV-RATE":
            continue
        st = _row_terminal_status(row)
        if st in ("FAIL", "INCOMPLETE"):
            return st
    if any(r.numeric_mismatch or r.shape_mismatch for r in rows):
        return "FAIL"
    return "PASS"


def _cd_subset_smoke_status(rows: list[MatrixRow], *, cells_compared: int) -> str:
    """Small cookbook C/D smoke: checker ran real comparisons without false PASS."""
    if cells_compared <= 0:
        return "INCOMPLETE"
    for row in rows:
        if row.rule_id not in MATRIX_EXEC_RULE_IDS:
            continue
        if row.cases_compared > 0 and row.case_failures == 0 and row.shape_mismatch == 0:
            return "PASS"
    return "INCOMPLETE"


def run_matrix(conn) -> dict[str, Any]:
    """Execute runner C/D comparisons; frozen A/B remain explicitly BLOCKED."""
    from scripts.ci import unit_contract_lib as uc  # noqa: PLC0415

    rows = build_matrix_rows()
    errors: list[str] = []
    cells_compared_total = 0
    cases_compared_total = 0
    attempted_total = 0
    required_total = 0
    a_status, b_detail = _frozen_ab_blocked()

    if conn is None:
        for row in rows:
            if row.tuner_effect == "unsupported" or row.rule_id == "SV-RATE":
                row.unsupported += 1
                row.status = "BLOCKED"
                row.runner_c = "BLOCKED"
                row.runner_d = "BLOCKED"
            elif row.rule_id not in MATRIX_EXEC_RULE_IDS:
                row.status = "SKIPPED"
                row.runner_c = "SKIPPED"
                row.runner_d = "SKIPPED"
            else:
                row.required += len(tuner_value_cases(None if row.tuner is None else {}))
                row.status = "PENDING"
                row.runner_c = "PENDING"
                row.runner_d = "PENDING"
            row.runner_a = a_status
            row.runner_b = a_status
            row.detail = b_detail
        return {
            "status": "INCOMPLETE",
            "cd_subset_smoke": "INCOMPLETE",
            "compared_cells": 0,
            "cases_compared": 0,
            "attempted": 0,
            "required": sum(r.required for r in rows),
            "errors": errors,
            "evidence": {
                "matrix_rows": len(rows),
                "cd_subset_scope": CD_SUBSET_SCOPE_NOTE,
                "runner_a_b": a_status,
                "runner_a_b_prerequisite": b_detail,
                "per_rule_tuner": [r.to_dict() for r in rows],
                "per_rule_tuner_totals": _totals(rows),
            },
        }

    metric = uc.load_json(uc.METRIC_UNITS)
    specs = _dataset_specs()
    for row in rows:
        if row.rule_id == "SV-RATE" or row.tuner_effect == "unsupported":
            row.status = "BLOCKED"
            row.runner_a = a_status
            row.runner_b = a_status
            row.runner_c = "BLOCKED"
            row.runner_d = "BLOCKED"
            row.unsupported += 1
            continue

        if row.rule_id not in MATRIX_EXEC_RULE_IDS:
            row.status = "SKIPPED"
            row.runner_a = a_status
            row.runner_b = a_status
            row.runner_c = "SKIPPED"
            row.runner_d = "SKIPPED"
            continue

        rule = next(r for r in cfl.load_rule_registry() if str(r.get("rule_id")) == row.rule_id)
        catalog_entry = next(
            e for e in json.loads((REPO / "sql" / "fdd" / "tuning_catalog.json").read_text())["rules"]
            if str(e.get("rule_id")) == row.rule_id
        )
        pspec = (catalog_entry.get("parameters") or {}).get(row.tuner or "") if row.tuner else None
        _reg_tuner, reg_err = _registry_param_for_catalog_tuner(rule, row.tuner)
        if reg_err:
            row.status = "INCOMPLETE"
            row.runner_a = a_status
            row.runner_b = a_status
            row.runner_c = "INCOMPLETE"
            row.runner_d = "INCOMPLETE"
            errors.append(reg_err)
            continue
        cases = tuner_value_cases(pspec if row.tuner else None)
        if row.tuner_effect == "no_op":
            cases = [cases[0]]
        eligible_specs: list[cfl.DatasetSpec] = []
        for spec in specs:
            ip_frame, _si_frame, _eid, _poll = _si_context(spec, metric)
            ok, _reason = cfl.rule_pair_eligible(
                rule, ip_frame, equipment_type=spec.equipment_type
            )
            if ok:
                eligible_specs.append(spec)
        if not eligible_specs:
            row.status = "SKIPPED"
            row.runner_a = a_status
            row.runner_b = a_status
            row.runner_c = "SKIPPED"
            row.runner_d = "SKIPPED"
            row.skipped += len(cases)
            continue

        row.required += len(cases) * len(eligible_specs)
        required_total += len(cases) * len(eligible_specs)

        for spec in eligible_specs:
            ip_frame, si_frame, equipment_id, poll = _si_context(spec, metric)
            for case_label, case_value in cases:
                row.attempted += 1
                attempted_total += 1
                case_result = _execute_cd_case(
                    conn,
                    spec,
                    rule,
                    si_frame=si_frame,
                    equipment_id=equipment_id,
                    poll=poll,
                    tuner_name=row.tuner,
                    tuner_value=case_value,
                    metric=metric,
                )
                prefix = f"{row.rule_id}/{row.tuner}/{case_label}@{spec.building_id}"
                if case_result.errors:
                    row.case_failures += 1
                    errors.extend(f"{prefix}: {e}" for e in case_result.errors)
                    continue
                daily = case_result.daily
                row.compared_cells += daily.compared_cells
                cells_compared_total += daily.compared_cells
                row.numeric_mismatch += daily.numeric_mismatch
                row.shape_mismatch += daily.shape_mismatch
                if case_result.both_empty:
                    row.case_insufficient += 1
                    errors.append(f"{prefix}: both sides empty — insufficient-data (no silent credit)")
                    continue
                if daily.total_mismatch:
                    errors.append(
                        f"{prefix}: shape={daily.shape_mismatch + daily.duplicate_keys} "
                        f"numeric={daily.numeric_mismatch} in {daily.compared_cells} cells"
                    )
                    row.case_failures += 1
                    continue
                if case_result.case_pass:
                    row.cases_compared += 1
                    cases_compared_total += 1

        row.runner_a = a_status
        row.runner_b = a_status
        row.status = _row_terminal_status(row)
        if row.status == "PASS":
            row.runner_c = "PASS"
            row.runner_d = "PASS"
        elif row.status == "FAIL":
            row.runner_c = "FAIL"
            row.runner_d = "FAIL"
        elif row.status == "INCOMPLETE":
            row.runner_c = "INCOMPLETE"
            row.runner_d = "INCOMPLETE"
        else:
            row.runner_c = row.status
            row.runner_d = row.status

    status = _aggregate_matrix_status(rows, cells_compared=cells_compared_total)
    smoke = _cd_subset_smoke_status(rows, cells_compared=cells_compared_total)

    return {
        "status": status,
        "cd_subset_smoke": smoke,
        "compared_cells": cells_compared_total,
        "cases_compared": cases_compared_total,
        "attempted": attempted_total,
        "required": required_total,
        "errors": errors,
        "evidence": {
            "matrix_rows": len(rows),
            "cd_subset_scope": CD_SUBSET_SCOPE_NOTE,
            "runner_a_b": a_status,
            "runner_a_b_prerequisite": b_detail,
            "per_rule_tuner_sample": [r.to_dict() for r in rows],
            "per_rule_tuner_totals": _totals(rows),
        },
    }


def _totals(rows: list[MatrixRow]) -> dict[str, int]:
    return {
        "required": sum(r.required for r in rows),
        "attempted": sum(r.attempted for r in rows),
        "cases_compared": sum(r.cases_compared for r in rows),
        "compared_cells": sum(r.compared_cells for r in rows),
        "numeric_mismatch": sum(r.numeric_mismatch for r in rows),
        "shape_mismatch": sum(r.shape_mismatch for r in rows),
        "case_failures": sum(r.case_failures for r in rows),
        "case_insufficient": sum(r.case_insufficient for r in rows),
        "skipped": sum(r.skipped for r in rows),
        "unsupported": sum(r.unsupported for r in rows),
    }


def mutation_self_credit_guard() -> tuple[int, list[str]]:
    """Positive control: offline matrix stays INCOMPLETE with zero runner C/D comparisons."""
    errors: list[str] = []
    offline = run_matrix(None)
    comparisons = 0
    if offline["compared_cells"] != 0:
        errors.append("offline SQL-QUAL-06 must not self-credit runner C/D comparisons")
    else:
        comparisons += 1
    if offline["status"] != "INCOMPLETE":
        errors.append(f"offline SQL-QUAL-06 expected INCOMPLETE, got {offline['status']!r}")
    else:
        comparisons += 1
    return comparisons, errors
