"""Unit tests for Bench 5007 long FDD validation (synthetic, no hardware)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pytest

from open_fdd.arrow_runtime.backend import run_arrow_rule
from open_fdd.arrow_runtime.confirmation import CONFIRMATION_ENGINE, confirm_fault_mask
from open_fdd.arrow_runtime.datafusion_backend import datafusion_available, run_datafusion_sql_rule
from open_fdd.arrow_runtime.execution_evidence import validate_computation_path
from open_fdd.validation.bench_5007_long_fdd import (
    SmokeConfig,
    ValidationReport,
    align_semantic_points,
    build_datafusion_threshold_sql,
    build_pyarrow_threshold_code,
    evaluate_backend_on_table,
    PointAlignment,
    render_markdown_report,
    run_synthetic_validation,
    summarize_report_dict,
    collect_verdict_errors,
    validate_confirmation_timing,
    write_report_artifacts,
)

REPO = Path(__file__).resolve().parents[3]
MODEL_PATH = REPO / "workspace" / "data" / "bench_dual_source_model.json"


@pytest.fixture
def bench_model() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def smoke_cfg() -> SmokeConfig:
    return SmokeConfig(
        duration_minutes=70,
        baseline_minutes=10,
        poll_seconds=60,
        confirmation_rows=10,
        confirmation_minutes=10.0,
        dry_run=True,
    )


def test_align_semantic_points_duct_t(bench_model: dict):
    aligned = align_semantic_points(bench_model, "demo")
    assert "duct-t" in aligned
    assert "bacnet_direct" in aligned["duct-t"]
    assert "niagara_baskstream" in aligned["duct-t"]
    assert aligned["duct-t"]["bacnet_direct"].point_id == "5007-analog-input-1192"


def test_confirmation_window_ten_rows():
    raw = pa.array([True] * 12, type=pa.bool_())
    confirmed, meta = confirm_fault_mask(raw, min_true_rows=10)
    assert meta["min_true_rows"] == 10
    # to_pylist() only after Arrow computation — assertion readability
    assert confirmed.to_pylist()[:9] == [False] * 9
    assert confirmed.to_pylist()[9] is True


def test_confirmation_resets_on_false():
    raw = pa.array([True, True, False, True, True, True, True, True, True, True], type=pa.bool_())
    confirmed, _ = confirm_fault_mask(raw, min_true_rows=3)
    # to_pylist() only after Arrow computation — assertion readability
    assert confirmed.to_pylist() == [False, False, False, False, False, True, True, True, True, True]


def test_pyarrow_datafusion_sql_recipes():
    code = build_pyarrow_threshold_code("duct-t", direction="below")
    sql = build_datafusion_threshold_sql("duct-t", 80.0, direction="below")
    assert "duct-t" in code
    assert '"duct-t" < 80.0' in sql or "duct-t < 80.0" in sql


def test_execution_evidence_rejects_python_list():
    errors = validate_computation_path({"computation_path": "python_list"})
    assert errors
    assert "python_list" in errors[0]


def test_execution_evidence_in_pyarrow_result():
    table = pa.table(
        {
            "timestamp": [f"2026-01-01T00:{i:02d}:00Z" for i in range(12)],
            "duct-t": [75.0] * 12,
        }
    )
    code = build_pyarrow_threshold_code("duct-t", direction="below")
    res = run_arrow_rule(code, table, {"threshold": 80.0, "min_true_rows": 10})
    ev = res.summary.get("execution_evidence") or {}
    assert ev.get("computation_path") == "pyarrow_compute"
    assert ev.get("confirmation_engine") == CONFIRMATION_ENGINE


@pytest.mark.skipif(not datafusion_available(), reason="DataFusion optional extra not installed")
def test_execution_evidence_in_datafusion_result():
    table = pa.table(
        {
            "timestamp": [f"2026-01-01T00:{i:02d}:00Z" for i in range(12)],
            "duct-t": [75.0] * 12,
        }
    )
    sql = build_datafusion_threshold_sql("duct-t", 80.0, direction="below")
    res = run_datafusion_sql_rule(sql, table, {"threshold": 80.0, "min_true_rows": 10})
    ev = res.summary.get("execution_evidence") or {}
    assert ev.get("computation_path") == "datafusion_sql"
    assert ev.get("confirmation_engine") == CONFIRMATION_ENGINE


def test_synthetic_validation_passes(smoke_cfg: SmokeConfig, bench_model: dict):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    assert report.verdict in ("PASS", "WARN")
    assert not report.errors
    assert len(report.matrix_runs) >= 2
    backends = {r.backend for r in report.matrix_runs}
    assert "pyarrow" in backends
    if datafusion_available():
        assert "datafusion_sql" in backends
        assert report.backend_equivalence
        assert report.backend_equivalence[0].pass_


def test_confirmation_warns_not_passes_if_python_loop(smoke_cfg: SmokeConfig, bench_model: dict):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    assert report.verdict == "WARN"
    assert any(CONFIRMATION_ENGINE in w for w in report.warnings)


def test_synthetic_report_contains_execution_evidence(smoke_cfg: SmokeConfig, bench_model: dict, tmp_path: Path):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    paths = write_report_artifacts(report, tmp_path)
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert "pyarrow_compute" in md
    assert "Fault confirmation window" in md or "confirmation window" in md.lower()
    assert CONFIRMATION_ENGINE in md
    if datafusion_available():
        assert "datafusion_sql" in md
    ev_rows = payload.get("execution_evidence") or []
    assert any(r.get("computation_path") == "pyarrow_compute" for r in ev_rows)


def test_no_secret_words_in_report_artifacts(smoke_cfg: SmokeConfig, bench_model: dict, tmp_path: Path):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    paths = write_report_artifacts(report, tmp_path)
    for key in ("markdown", "json", "csv"):
        text = Path(paths[key]).read_text(encoding="utf-8").lower()
        for needle in ("password", "bearer_token", "access_token", "refresh_token", "api_key"):
            assert needle not in text


def test_confirmation_timestamp_not_before_window(smoke_cfg: SmokeConfig):
    """1-minute timestamps: confirmed fault not before baseline + confirmation rows."""
    baseline_rows = 20
    total_rows = baseline_rows + smoke_cfg.confirmation_rows + 5
    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [
        (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z") for i in range(total_rows)
    ]
    values = [90.0] * baseline_rows + [75.0] * (total_rows - baseline_rows)
    table = pa.table({"timestamp": timestamps, "duct-t": values})
    alignment = PointAlignment(
        semantic_key="duct-t",
        source="bacnet_direct",
        point_id="synthetic",
        equipment_id="bacnet-5007",
        historian_column="duct-t",
        brick_type="Discharge_Air_Temperature_Sensor",
        fdd_input="duct-t",
    )
    metrics = evaluate_backend_on_table(
        table,
        alignment=alignment,
        backend="pyarrow",
        cfg=smoke_cfg,
        threshold=80.0,
        phase="fault",
    )
    assert not metrics.errors
    assert metrics.first_raw_fault_time
    assert metrics.first_confirmed_fault_time
    threshold_change = timestamps[baseline_rows]
    assert metrics.first_raw_fault_time >= threshold_change
    # 10 consecutive minutes after change → confirmed at or after row baseline+9
    expected_earliest = timestamps[baseline_rows + smoke_cfg.confirmation_rows - 1]
    assert metrics.first_confirmed_fault_time >= expected_earliest


def test_confirmation_timing_helper(smoke_cfg: SmokeConfig):
    from open_fdd.validation.bench_5007_long_fdd import build_synthetic_dual_tables

    baseline_rows = 10
    total_rows = 30
    tables = build_synthetic_dual_tables(smoke_cfg, total_rows=total_rows, baseline_rows=baseline_rows)
    errors = validate_confirmation_timing(
        tables["bacnet_direct"],
        cfg=smoke_cfg,
        threshold=80.0,
        baseline_rows=baseline_rows,
    )
    assert not errors


def test_report_artifacts(smoke_cfg: SmokeConfig, bench_model: dict, tmp_path: Path):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    paths = write_report_artifacts(report, tmp_path)
    assert Path(paths["markdown"]).is_file()
    assert Path(paths["json"]).is_file()
    assert Path(paths["csv"]).is_file()
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "confirmation window" in md.lower()
    assert "Bench 5007 Long FDD Smoke Report" in md
    assert render_markdown_report(report)


def test_smoke_script_synthetic_subprocess():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "smoke_bench_5007_long_fdd.py"), "--synthetic", "--dry-run"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "LONG FDD SMOKE" in proc.stdout
    assert "password" not in proc.stdout.lower() or "********" in proc.stdout


def test_summarize_report_dict(smoke_cfg: SmokeConfig, bench_model: dict):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    payload = report.to_dict()
    summary = summarize_report_dict(payload)
    assert summary["verdict"] in ("PASS", "WARN")
    assert summary["matrix_runs"] >= 2
    assert summary["pyarrow_rows"] > 0
    assert summary["csv_event_rows"] >= 3


def test_collect_verdict_errors_live_empty():
    report = ValidationReport(
        config=SmokeConfig(duration_minutes=120),
        environment={"mode": "live"},
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T02:00:00+00:00",
    )
    errors = collect_verdict_errors(report)
    assert any("matrix_runs empty" in e for e in errors)


def test_inspect_script_subprocess(smoke_cfg: SmokeConfig, bench_model: dict, tmp_path: Path):
    report = run_synthetic_validation(smoke_cfg, model=bench_model)
    paths = write_report_artifacts(report, tmp_path)
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "inspect_bench_5007_long_fdd_report.py"), paths["json"]],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "verdict:" in proc.stdout
    assert "matrix_runs:" in proc.stdout
