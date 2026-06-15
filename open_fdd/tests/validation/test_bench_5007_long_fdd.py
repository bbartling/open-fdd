"""Unit tests for Bench 5007 long FDD validation (synthetic, no hardware)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest

from open_fdd.arrow_runtime.confirmation import confirm_fault_mask
from open_fdd.arrow_runtime.datafusion_backend import datafusion_available
from open_fdd.validation.bench_5007_long_fdd import (
    SmokeConfig,
    align_semantic_points,
    build_datafusion_threshold_sql,
    build_pyarrow_threshold_code,
    render_markdown_report,
    run_synthetic_validation,
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
    assert confirmed.to_pylist()[:9] == [False] * 9
    assert confirmed.to_pylist()[9] is True


def test_confirmation_resets_on_false():
    raw = pa.array([True, True, False, True, True, True, True, True, True, True], type=pa.bool_())
    confirmed, _ = confirm_fault_mask(raw, min_true_rows=3)
    assert confirmed.to_pylist() == [False, False, False, False, False, True, True, True, True, True]


def test_pyarrow_datafusion_sql_recipes():
    code = build_pyarrow_threshold_code("duct-t", direction="below")
    sql = build_datafusion_threshold_sql("duct-t", 80.0, direction="below")
    assert "duct-t" in code
    assert '"duct-t" < 80.0' in sql or "duct-t < 80.0" in sql


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
    assert "Fault confirmation window" in md or "confirmation window" in md.lower()
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
