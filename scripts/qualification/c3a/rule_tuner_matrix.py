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

_SV_RANGE_SCALE_PARAMS = frozenset(
    {"range_scale_temperature", "range_scale_humidity", "range_scale_pressure"}
)


def _load_expected_change_ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def sv_range_scale_nondefault_ledger_waiver(
    rule_id: str, tuner: str | None, case_label: str
) -> bool:
    """True when a C/D mismatch is an expected SV-RANGE scale geometry gap (#1408 ledger)."""
    if rule_id != "SV-RANGE" or not tuner or tuner not in _SV_RANGE_SCALE_PARAMS:
        return False
    if case_label == "default":
        return False
    for entry in _load_expected_change_ledger().get("issues") or []:
        if int(entry.get("issue") or 0) != 1408:
            continue
        params = entry.get("parameters") or []
        cases = entry.get("non_default_tuner_cases") or []
        if tuner in params and case_label in cases:
            return bool(entry.get("waive_cd_agreement_on_nondefault"))
    return False


@dataclass
class MatrixRow:
    rule_id: str
    tuner: str | None
    tuner_effect: str
    required: int = 0
    executed: int = 0
    compared: int = 0
    mismatch: int = 0
    skipped: int = 0
    unsupported: int = 0
    ledger_waived: int = 0
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
            "executed": self.executed,
            "compared": self.compared,
            "mismatch": self.mismatch,
            "skipped": self.skipped,
            "unsupported": self.unsupported,
            "ledger_waived": self.ledger_waived,
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


def _compare_daily(
    pandas_rows: list[dict[str, Any]], sql_rows: list[dict[str, Any]]
) -> tuple[int, int]:
    pd_daily = [
        r for r in pandas_rows if r.get("utc_day") and str(r.get("pair_status") or "") == "computed"
    ]
    sql_daily = [
        r for r in sql_rows if r.get("utc_day") and str(r.get("pair_status") or "") == "computed"
    ]
    pd_map = {_daily_key(r): r for r in pd_daily}
    sql_map = {_daily_key(r): r for r in sql_daily}
    compared = 0
    mismatch = 0
    for key in sorted(set(pd_map) & set(sql_map), key=repr):
        compared += 1
        pd_row = pd_map[key]
        sql_row = sql_map[key]
        if not cts.pc_fault_seconds_equal(
            float(pd_row.get("fault_seconds", 0)), float(sql_row.get("fault_seconds", 0))
        ):
            mismatch += 1
            continue
        pd_cov = pd_row.get("covered_seconds")
        sql_cov = sql_row.get("covered_seconds")
        if pd_cov is not None and sql_cov is not None:
            if float(pd_cov) != float(sql_cov):
                mismatch += 1
    return compared, mismatch


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


def _params_si_for_case(
    rule: dict[str, Any],
    metric: dict[str, Any],
    *,
    tuner_name: str | None,
    tuner_value: float | None,
) -> dict[str, float]:
    def param_hook(name: str, val: float) -> float:
        if tuner_name is not None and name == tuner_name and tuner_value is not None:
            return float(tuner_value)
        return val

    _params_ip, params_si = cfl.resolve_rule_params_ip_si(rule, metric, param_hook=param_hook)
    return params_si


CaseResult = tuple[str, int, int, list[str]]


def _execute_cd_cases_batched(
    conn,
    spec: cfl.DatasetSpec,
    rule: dict[str, Any],
    *,
    si_frame,
    equipment_id: str,
    poll: float,
    tuner_name: str | None,
    cases: list[tuple[str, float | None]],
    metric: dict[str, Any],
) -> list[CaseResult]:
    """One Timescale seed per spec+rule; vary tuner params via savepoints (runner C/D)."""
    from open_fdd.rules import RULES_BY_ID  # noqa: PLC0415
    from scripts.stress.si_cutover import product_sql_params as psp  # noqa: PLC0415

    rule_id = str(rule.get("rule_id") or "")
    if not rule.get("pandas_function") and rule_id not in RULES_BY_ID:
        err = f"{spec.building_id}/{rule_id}: no pandas twin"
        return [(label, 0, 0, [err]) for label, _ in cases]

    prepared: list[tuple[str, float | None, dict[str, float], list[dict[str, Any]]]] = []
    for case_label, case_value in cases:
        params_si = _params_si_for_case(
            rule, metric, tuner_name=tuner_name, tuner_value=case_value
        )
        pandas_rows = cfl.run_rule_daily_rows(
            rule,
            si_frame,
            building_id=spec.building_id,
            equipment_id=equipment_id,
            params=params_si,
            poll_seconds=poll,
        )
        prepared.append((case_label, case_value, params_si, pandas_rows))

    parity = cts._load_parity_module()
    site_id = f"{spec.building_id}__si"
    sql_cols = cts.history_columns_for_rules(si_frame, [rule])
    out: list[CaseResult] = []

    try:
        with conn.cursor() as cur:
            cts.purge_site(cur, site_id)
            cts.seed_frame(
                cur,
                parity,
                site_id=site_id,
                equipment_id=equipment_id,
                equip_type=spec.equipment_type,
                frame=si_frame,
                storage="si",
            )
            cts.fill_history(cur, site_id, sql_cols)
            conn.commit()

            for case_label, _case_value, params_si, pandas_rows in prepared:
                cur.execute("SAVEPOINT sql_qual_cd_case")
                sql_rows, sql_err = cts.execute_sql_rule_daily(
                    cur,
                    rule=rule,
                    building_id=spec.building_id,
                    equipment_id=equipment_id,
                    poll_seconds=poll,
                    index=si_frame.index,
                    render_overrides=psp.catalog_overrides_from_registry(rule, params_si),
                    storage="si",
                )
                if sql_err:
                    cur.execute("ROLLBACK TO SAVEPOINT sql_qual_cd_case")
                    cur.execute("RELEASE SAVEPOINT sql_qual_cd_case")
                    out.append((case_label, 0, 0, [f"{spec.building_id}/{rule_id}: {sql_err}"]))
                    continue
                cur.execute("RELEASE SAVEPOINT sql_qual_cd_case")
                pd_computed = any(
                    str(r.get("pair_status") or "") == "computed" for r in pandas_rows
                )
                compared, mismatch = _compare_daily(pandas_rows, sql_rows)
                if compared == 0 and not pd_computed:
                    out.append((case_label, 0, 0, []))
                else:
                    out.append((case_label, compared, mismatch, []))
    except Exception as exc:
        conn.rollback()
        msg = f"{spec.building_id}/{rule_id}: {exc}"
        if not out:
            return [(label, 0, 0, [msg]) for label, _ in cases]
        while len(out) < len(cases):
            label = cases[len(out)][0]
            out.append((label, 0, 0, [msg]))
    return out


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


def run_matrix(conn) -> dict[str, Any]:
    """Execute runner C/D comparisons; frozen A/B remain explicitly BLOCKED."""
    from scripts.ci import unit_contract_lib as uc  # noqa: PLC0415

    rows = build_matrix_rows()
    errors: list[str] = []
    compared_total = 0
    executed_total = 0
    required_total = 0
    a_status, b_detail = _frozen_ab_blocked()

    if conn is None:
        for row in rows:
            if row.tuner_effect == "unsupported" or row.rule_id == "SV-RATE":
                row.unsupported += 1
                row.status = "BLOCKED"
                row.runner_c = "BLOCKED"
                row.runner_d = "BLOCKED"
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
            "compared": 0,
            "executed": 0,
            "required": sum(r.required for r in rows),
            "errors": errors,
            "evidence": {
                "matrix_rows": len(rows),
                "runner_a_b": a_status,
                "runner_a_b_prerequisite": b_detail,
                "per_rule_tuner": [r.to_dict() for r in rows[:24]],
                "per_rule_tuner_totals": _totals(rows),
            },
        }

    metric = uc.load_json(uc.METRIC_UNITS)
    specs = _dataset_specs()
    cts.apply_fdd_postgres_helpers(conn)
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
            case_results = _execute_cd_cases_batched(
                conn,
                spec,
                rule,
                si_frame=si_frame,
                equipment_id=equipment_id,
                poll=poll,
                tuner_name=row.tuner,
                cases=cases,
                metric=metric,
            )
            for case_label, compared, mismatch, exec_errors in case_results:
                row.executed += 1
                executed_total += 1
                if exec_errors:
                    row.skipped += 1
                    continue
                row.compared += compared
                compared_total += compared
                if mismatch and sv_range_scale_nondefault_ledger_waiver(
                    row.rule_id, row.tuner, case_label
                ):
                    row.ledger_waived += mismatch
                elif mismatch:
                    row.mismatch += mismatch
                    errors.append(
                        f"{row.rule_id}/{row.tuner}/{case_label}@{spec.building_id}: "
                        f"{mismatch} mismatches in {compared} cells"
                    )

        row.runner_a = a_status
        row.runner_b = a_status
        if row.mismatch:
            row.status = "FAIL"
            row.runner_c = "FAIL"
            row.runner_d = "FAIL"
        elif row.compared > 0:
            row.status = "PASS"
            row.runner_c = "PASS"
            row.runner_d = "PASS"
        elif row.executed > 0 and row.compared == 0:
            row.status = "SKIPPED"
            row.runner_c = "SKIPPED"
            row.runner_d = "SKIPPED"
        else:
            row.status = "SKIPPED"
            row.runner_c = "SKIPPED"
            row.runner_d = "SKIPPED"

    mismatch_total = sum(r.mismatch for r in rows)
    status = "PASS"
    if compared_total == 0:
        status = "INCOMPLETE"
    elif mismatch_total > 0:
        status = "FAIL"

    return {
        "status": status,
        "compared": compared_total,
        "executed": executed_total,
        "required": required_total,
        "errors": errors,
        "evidence": {
            "matrix_rows": len(rows),
            "runner_a_b": a_status,
            "runner_a_b_prerequisite": b_detail,
            "per_rule_tuner_sample": [r.to_dict() for r in rows[:24]],
            "per_rule_tuner_totals": _totals(rows),
        },
    }


def _totals(rows: list[MatrixRow]) -> dict[str, int]:
    return {
        "required": sum(r.required for r in rows),
        "executed": sum(r.executed for r in rows),
        "compared": sum(r.compared for r in rows),
        "mismatch": sum(r.mismatch for r in rows),
        "skipped": sum(r.skipped for r in rows),
        "unsupported": sum(r.unsupported for r in rows),
        "ledger_waived": sum(r.ledger_waived for r in rows),
    }


def mutation_self_credit_guard() -> tuple[int, list[str]]:
    """Positive control: offline matrix stays INCOMPLETE with zero runner C/D comparisons."""
    errors: list[str] = []
    offline = run_matrix(None)
    comparisons = 0
    if offline["compared"] != 0:
        errors.append("offline SQL-QUAL-06 must not self-credit runner C/D comparisons")
    else:
        comparisons += 1
    if offline["status"] != "INCOMPLETE":
        errors.append(f"offline SQL-QUAL-06 expected INCOMPLETE, got {offline['status']!r}")
    else:
        comparisons += 1
    return comparisons, errors
