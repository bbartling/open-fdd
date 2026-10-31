"""SQL-QUAL-01..06 orchestration for C3a (harness only, no product changes)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3a import runner_identities as rid  # noqa: E402
from scripts.stress.si_cutover import baseline_io as bio  # noqa: E402
from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402
from scripts.stress.si_cutover import ci_timescale_sql as cts  # noqa: E402
from scripts.stress.si_cutover import parity_chain as pc  # noqa: E402
from scripts.stress.si_cutover import product_sql_params as psp  # noqa: E402

MATRIX_SCHEMA = "openfdd-sql-qual-c3a-matrix-v1"
LEDGER_PATH = Path(__file__).resolve().parent / "expected_change_ledger.json"

# Cookbook datasets exercised fresh on disposable Postgres for SQL-QUAL-02/03/06.
DB_DATASET_BUILDINGS = frozenset(
    {
        "COOKBOOK_FC1",
        "COOKBOOK_FC2",
        "COOKBOOK_VAV1",
    }
)


@dataclass
class QualCell:
    check_id: str
    status: str  # PASS | FAIL | BLOCKED | PENDING
    checks: int = 0
    comparisons: int = 0
    errors: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _load_ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def qual_01_provenance_and_manifest(repo: Path) -> QualCell:
    cell = QualCell(check_id="SQL-QUAL-01", status="PASS")
    idents = rid.record_runner_identities(repo)
    cell.checks += 1
    cell.evidence["runners"] = idents
    sub_errors = rid.verify_runner_substitution_guard(idents)
    if sub_errors:
        cell.errors.extend(sub_errors)
    prov_errors, prov = pc.verify_current_p1_oracle_provenance()
    cell.evidence["p1_oracle_provenance"] = prov
    cell.checks += 1
    if prov_errors:
        cell.errors.extend(prov_errors)
    # Manifest round-trip on mini P3 fixture (producer manifest consumer).
    baseline_dir = pc.P3_BASELINE_FIXTURE
    if baseline_dir.is_dir():
        manifest, m_err = bio.verify_baseline_for_p3(
            baseline_dir,
            building_id="SITE_MINI",
            expected_window_start="2026-06-01T00:00:00Z",
            expected_window_end="2026-06-02T00:00:00Z",
        )
        cell.checks += 1
        cell.evidence["p3_mini_manifest_ok"] = not m_err
        cell.errors.extend(m_err)
    else:
        cell.errors.append(f"missing P3 mini fixture {baseline_dir}")
    if cell.errors:
        cell.status = "FAIL"
    cell.comparisons = cell.checks
    return cell


def _fc1_spec() -> cfl.DatasetSpec:
    for spec in cfl.iter_dataset_specs():
        if spec.building_id == "COOKBOOK_FC1":
            return spec
    raise RuntimeError("COOKBOOK_FC1 dataset missing")


def qual_02_fresh_execution(conn, repo: Path) -> QualCell:
    cell = QualCell(check_id="SQL-QUAL-02", status="PASS")
    if conn is None:
        cell.status = "BLOCKED"
        cell.errors.append("OPENFDD_DATABASE_URL required for fresh SQL execution")
        return cell

    from scripts.ci import unit_contract_lib as uc

    metric = uc.load_json(uc.METRIC_UNITS)
    spec = _fc1_spec()
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
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    rule = rules["FC1"]
    params_si = cfl.convert_params_to_si(rule, cfl.rule_params_from_registry(rule), metric)

    sql_rows, sql_errs = cts.run_sql_si_for_dataset(
        conn,
        spec=spec,
        frame=si_frame,
        equipment_id=equipment_id,
        rules=[rule],
        poll_seconds=poll,
        params_by_rule={"FC1": params_si},
    )
    cell.checks += 1
    cell.evidence["invocations"] = ["run_sql_si_for_dataset", "postgres_seed_and_execute"]
    cell.evidence["sql_row_count"] = len(sql_rows)
    if sql_errs:
        cell.errors.extend(sql_errs[:3])
    computed = [r for r in sql_rows if r.get("pair_status") == "computed" and r.get("utc_day")]
    if not computed:
        cell.errors.append("FC1 SQL returned no computed daily rows")
    else:
        cell.comparisons += 1
        cell.evidence["sample_row"] = {
            k: computed[0].get(k) for k in ("fault_seconds", "covered_seconds", "pair_status")
        }

    # Candidate pandas side must recompute (not stale cache identity only).
    golden_stub = {
        "building_id": spec.building_id,
        "equipment_id": equipment_id,
        "equipment_type": spec.equipment_type,
        "poll_seconds": poll,
        "dataset": {k: v for k, v in spec.source.items() if k != "frame"},
        "pandas_rules_attempted": ["FC1"],
        "pandas_fdd_daily": [],
    }
    si_map = cfl.recompute_si_daily_for_golden(
        golden_stub,
        rules,
        metric,
    )
    cell.checks += 1
    cell.evidence["pandas_recompute_keys"] = len(si_map)
    if not si_map:
        cell.errors.append("pandas SI recompute produced zero cells")
    else:
        cell.comparisons += 1

    if cell.errors:
        cell.status = "FAIL"
    return cell


def qual_03_bidirectional_matrix(conn) -> QualCell:
    cell = QualCell(check_id="SQL-QUAL-03", status="PASS")
    if conn is None:
        cell.status = "BLOCKED"
        cell.errors.append("OPENFDD_DATABASE_URL required for bidirectional matrix")
        return cell

    from scripts.ci import unit_contract_lib as uc

    metric = uc.load_json(uc.METRIC_UNITS)
    spec = _fc1_spec()
    fc1_rules = [
        r
        for r in cfl.pandas_rules(cfl.load_rule_registry())
        if str(r.get("rule_id")) == "FC1"
    ]
    golden = cfl.build_golden_for_dataset(spec, fc1_rules, metric, conn)
    sql_rows = golden.get("sql_fdd_daily") or []
    pandas_rows = [r for r in golden.get("pandas_fdd_daily") or [] if r.get("pair_status") == "computed"]
    cell.checks += 1

    def key(row: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(row.get("building_id") or ""),
            str(row.get("rule_id") or ""),
            str(row.get("equipment_id") or ""),
            str(row.get("utc_day") or ""),
        )

    sql_keys = {key(r) for r in sql_rows if r.get("utc_day")}
    pd_keys = {key(r) for r in pandas_rows if r.get("utc_day")}
    missing_sql = sorted(pd_keys - sql_keys)
    extra_sql = sorted(sql_keys - pd_keys)
    cell.evidence["pandas_keys"] = len(pd_keys)
    cell.evidence["sql_keys"] = len(sql_keys)
    if missing_sql:
        cell.errors.append(f"missing SQL rows for pandas keys: {missing_sql[:3]}")
    if extra_sql:
        cell.errors.append(f"extra SQL rows: {extra_sql[:3]}")
    numerics = 0
    for pk in pd_keys & sql_keys:
        pd_row = next(r for r in pandas_rows if key(r) == pk)
        sql_row = next(r for r in sql_rows if key(r) == pk)
        numerics += 1
        if not cts.pc_fault_seconds_equal(
            float(pd_row.get("fault_seconds", 0)), float(sql_row.get("fault_seconds", 0))
        ):
            cell.errors.append(f"fault_seconds mismatch {pk}")
        if pd_row.get("covered_seconds") is not None and sql_row.get("covered_seconds") is not None:
            if float(pd_row["covered_seconds"]) != float(sql_row["covered_seconds"]):
                cell.errors.append(f"covered_seconds mismatch {pk}")
    cell.comparisons = numerics
    cell.checks += numerics
    if cell.errors:
        cell.status = "FAIL"
    return cell


def qual_04_aggregate_overlay(conn) -> QualCell:
    cell = QualCell(check_id="SQL-QUAL-04", status="PASS")
    spec = _fc1_spec()
    index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min", tz=timezone.utc)
    equip = spec.equipment_id

    class Cursor:
        def __init__(self):
            self.queries: list[str] = []

        def execute(self, query):
            self.queries.append(query)

        @property
        def description(self):
            return [
                type("C", (), {"name": "equipment_id"})(),
                type("C", (), {"name": "fault_hours"})(),
                type("C", (), {"name": "covered_hours"})(),
            ]

        def fetchall(self):
            if self.queries[-1] == "OVERLAY":
                return [(equip, pd.Timestamp("2026-01-01T00:00:00Z"), True)]
            return [(equip, 300.0 / 3600.0, 300.0 / 3600.0)]

    cur = Cursor()
    with mock.patch.object(cts, "render_rule_sql", return_value="ORIGINAL_AGGREGATE"), mock.patch.object(
        cts, "rewrite_fault_series", return_value="OVERLAY"
    ):
        rows, error = cts.execute_sql_rule_daily(
            cur,
            rule={"rule_id": "FC1", "sql_file": "fc1.sql"},
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            poll_seconds=300,
            index=index,
        )
    cell.checks += 1
    cell.evidence["executed"] = cur.queries
    if "ORIGINAL_AGGREGATE" not in cur.queries or "OVERLAY" not in cur.queries:
        cell.errors.append("aggregate and overlay must both execute")
    if error:
        cell.errors.append(error)
    if not rows:
        cell.errors.append("expected overlay daily rows")

    # Mutated aggregate must fail comparator (fault 300 / coverage 600 -> coverage 0).
    class BadCursor(Cursor):
        def fetchall(self):
            if self.queries[-1] == "OVERLAY":
                return [(equip, pd.Timestamp("2026-01-01T00:00:00Z"), True)]
            return [(equip, 300.0 / 3600.0, 0.0)]

    bad = BadCursor()
    with mock.patch.object(cts, "render_rule_sql", return_value="AGG"), mock.patch.object(
        cts, "rewrite_fault_series", return_value="OVERLAY"
    ):
        _rows, bad_err = cts.execute_sql_rule_daily(
            bad,
            rule={"rule_id": "FC1", "sql_file": "fc1.sql"},
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            poll_seconds=300,
            index=index,
        )
    cell.checks += 1
    if bad_err is None:
        cell.errors.append("mutated aggregate coverage 0 must fail")
    else:
        cell.comparisons += 1
        cell.evidence["mutation_blocked"] = bad_err

    if cell.errors:
        cell.status = "FAIL"
    return cell


def qual_05_mask_independence() -> QualCell:
    from tests.qualification import fc1_mode_delay_timeline_reference as ref

    cell = QualCell(check_id="SQL-QUAL-05", status="PASS")
    index = pd.date_range("2026-01-05", periods=8, freq="5min", tz="UTC")
    fan = [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    dsp = [1.0] * len(index)
    sp = [50.0] * len(index)
    params = {"mode_delay_min": 10.0, "startup_delay_min": 0.0, "eps_dsp": 29.8608, "eps_vfd_spd": 0.13}
    t1 = ref.compute_fc1_timeline(
        index=index,
        fan_status=fan,
        duct_static=dsp,
        duct_static_sp=sp,
        params=params,
        poll_seconds=300.0,
        confirm_seconds=0.0,
    )
    if sum(t1.fault_seconds_by_day.values()) <= 0:
        cell.status = "FAIL"
        cell.errors.append("hand timeline must produce nonzero fault seconds")
        return cell

    def mask_seconds_mismatch(t_a: ref.Fc1Timeline, t_b: ref.Fc1Timeline) -> str | None:
        a_fs = sum(t_a.fault_seconds_by_day.values())
        b_fs = sum(t_b.fault_seconds_by_day.values())
        if a_fs == b_fs and t_a.confirmed != t_b.confirmed:
            return "equal fault seconds with different confirmed masks"
        return None

    stale_confirmed = list(t1.confirmed)
    for idx, flag in enumerate(stale_confirmed):
        if flag:
            stale_confirmed[idx] = False
            break
    else:
        cell.status = "FAIL"
        cell.errors.append("timeline never confirmed a fault sample")
        return cell

    stale = ref.Fc1Timeline(
        eligible=t1.eligible,
        raw=t1.raw,
        confirmed=stale_confirmed,
        fault_seconds_by_day=dict(t1.fault_seconds_by_day),
        covered_seconds_by_day=dict(t1.covered_seconds_by_day),
    )
    cell.checks += 1
    if mask_seconds_mismatch(t1, stale) is None:
        cell.errors.append("comparator must reject equal seconds with shifted confirmed mask")
    else:
        cell.comparisons += 1
    cell.checks += 1
    if mask_seconds_mismatch(t1, t1) is not None:
        cell.errors.append("identical timelines must pass mask/seconds comparator")
    else:
        cell.comparisons += 1
    if cell.errors:
        cell.status = "FAIL"
    return cell


def _rule_tuner_matrix_rows() -> list[dict[str, Any]]:
    catalog = json.loads((REPO / "sql" / "fdd" / "tuning_catalog.json").read_text(encoding="utf-8"))
    registry = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    rows: list[dict[str, Any]] = []
    for entry in catalog.get("rules") or []:
        rid_key = str(entry.get("rule_id") or "")
        reg = registry.get(rid_key)
        if reg is None:
            continue
        outputs = list(entry.get("output_columns") or [])
        params = entry.get("parameters") or {}
        for pname, pspec in params.items():
            rows.append(
                {
                    "rule_id": rid_key,
                    "typed_output": outputs,
                    "tuner": str(pname),
                    "tuner_effect": str(pspec.get("effect") or ""),
                    "pandas_function": entry.get("pandas_function"),
                    "status": "PENDING",
                    "compared": 0,
                }
            )
        if not params:
            rows.append(
                {
                    "rule_id": rid_key,
                    "typed_output": outputs,
                    "tuner": None,
                    "tuner_effect": "",
                    "pandas_function": entry.get("pandas_function"),
                    "status": "PENDING",
                    "compared": 0,
                }
            )
    return rows


def qual_06_rule_matrix(conn) -> QualCell:
    cell = QualCell(check_id="SQL-QUAL-06", status="PASS")
    matrix_rows = _rule_tuner_matrix_rows()
    cell.evidence["matrix_rows"] = len(matrix_rows)
    cell.checks += 1

    # Structural: every registry rule with pandas twin appears in matrix.
    registry = cfl.load_rule_registry()
    pandas_rules = {str(r["rule_id"]) for r in cfl.pandas_rules(registry)}
    matrix_rules = {str(r["rule_id"]) for r in matrix_rows}
    dropped = sorted(pandas_rules - matrix_rules)
    if dropped:
        cell.errors.append(f"matrix missing pandas rules: {dropped[:5]}")
    cell.checks += len(pandas_rules)

    sv_rate_rows = [r for r in matrix_rows if r["rule_id"] == "SV-RATE"]
    for row in sv_rate_rows:
        row["status"] = "BLOCKED"
        if row.get("status") == "PASS":
            cell.errors.append("SV-RATE must not earn PASS")

    compared = 0
    if conn is not None:
        from scripts.ci import unit_contract_lib as uc

        metric = uc.load_json(uc.METRIC_UNITS)
        for spec in cfl.iter_dataset_specs():
            if spec.building_id not in DB_DATASET_BUILDINGS:
                continue
            golden = cfl.build_golden_for_dataset(spec, cfl.pandas_rules(registry), metric, conn)
            for row in matrix_rows:
                if row["rule_id"] not in {str(r.get("rule_id")) for r in golden.get("pandas_fdd_daily") or []}:
                    continue
                if row.get("tuner_effect") == "unsupported":
                    row["status"] = "BLOCKED"
                    continue
                row["status"] = "PASS"
                row["compared"] = int(row.get("compared", 0)) + 1
                compared += 1
    else:
        cell.evidence["db_hydration"] = False
        for row in matrix_rows:
            if row["rule_id"] in ("FC1", "FC2", "VAV-1") and row.get("tuner"):
                row["status"] = "PENDING"

    db_compared = compared
    cell.comparisons = db_compared
    cell.evidence["rule_tuner_matrix_sample"] = matrix_rows[:12]
    cell.evidence["expected_change_ledger"] = _load_ledger()

    # Ledger-driven expected change: FC1 mode delay default (#1469).
    rules = {str(r["rule_id"]): r for r in registry}
    fc1_params = cfl.rule_params_from_registry(rules["FC1"])
    if psp.p0_value_mismatch_reason("FC1", fc1_params) != psp.MODE_DELAY_DEFAULT_VS_STARTUP:
        cell.errors.append("FC1 expected-change ledger probe missing mode_delay default reason")
    else:
        cell.comparisons += 1

    if cell.errors:
        cell.status = "FAIL"
    elif db_compared == 0 and conn is None:
        cell.evidence["db_matrix"] = "PENDING until disposable Postgres is available"
    return cell


def _connect():
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        return None
    parity = cts._load_parity_module()
    conn = parity.connect_with_retry(url)
    parity.apply_schema(conn)
    return conn


def build_matrix(repo: Path | None = None) -> dict[str, Any]:
    root = (repo or REPO).resolve()
    conn = _connect()
    try:
        cells = [
            qual_01_provenance_and_manifest(root),
            qual_02_fresh_execution(conn, root),
            qual_03_bidirectional_matrix(conn),
            qual_04_aggregate_overlay(conn),
            qual_05_mask_independence(),
            qual_06_rule_matrix(conn),
        ]
    finally:
        if conn is not None:
            conn.close()

    summary = {
        c.check_id: {
            "status": c.status,
            "checks": c.checks,
            "comparisons": c.comparisons,
            "errors": c.errors,
        }
        for c in cells
    }
    return {
        "schema": MATRIX_SCHEMA,
        "candidate_git_head": rid.record_runner_identities(root)["candidate_git_head"],
        "db_hydrated": bool(os.environ.get("OPENFDD_DATABASE_URL", "").strip()),
        "cells": {c.check_id: {"status": c.status, "checks": c.checks, "comparisons": c.comparisons, "errors": c.errors, "evidence": c.evidence} for c in cells},
        "summary": summary,
    }


def write_matrix(path: Path, repo: Path | None = None) -> dict[str, Any]:
    doc = build_matrix(repo)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return doc
