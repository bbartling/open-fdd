from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pyarrow as pa
import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _reload_playground() -> None:
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]


@pytest.fixture
def subprocess_playground(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFDD_PLAYGROUND_INPROCESS", raising=False)
    monkeypatch.setenv("OFDD_PLAYGROUND_SUBPROCESS", "1")
    monkeypatch.setenv("OFDD_PLAYGROUND_TIMEOUT_S", "3")
    _reload_playground()


def test_subprocess_worker_runs_arrow(subprocess_playground):
    from openfdd_bridge.playground import run_arrow_table  # noqa: E402

    table = pa.table({"SAT": pa.array([80.0], type=pa.float64())})
    code = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(pc.cast(table["SAT"], pa.float64()), float(cfg.get("high", 75)))
"""
    result = run_arrow_table(code, table, {"high": 75})
    assert result["ok"] is True
    assert result["flagged"] == 1


def test_subprocess_infinite_loop_times_out(subprocess_playground):
    from openfdd_bridge.playground import run_arrow_table  # noqa: E402

    table = pa.table({"SAT": pa.array([72.0], type=pa.float64())})
    code = "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    while True:\n        pass\n    return pc.greater(table['SAT'], 0)\n"
    started = time.time()
    result = run_arrow_table(code, table, {})
    elapsed = time.time() - started
    assert elapsed < 25.0
    assert result["ok"] is False
    assert "timed out" in str(result.get("error", "")).lower()


def test_subprocess_rejects_import_os(subprocess_playground):
    from openfdd_bridge.playground import run_arrow_table  # noqa: E402

    table = pa.table({"SAT": pa.array([1.0], type=pa.float64())})
    code = "import os\nimport pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return False\n"
    result = run_arrow_table(code, table, {})
    assert result["ok"] is False
    assert result.get("issues") or result.get("error")


def test_subprocess_run_script(subprocess_playground, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_PLAYGROUND_TIMEOUT_S", "15")
    _reload_playground()
    from openfdd_bridge.playground import run_arrow_script  # noqa: E402

    table = pa.table({"SAT": pa.array([70.0, 85.0], type=pa.float64())})
    code = """
out = {"events": [{"type": "metrics", "metrics": {"rows": table.num_rows}}], "metrics": {"rows": table.num_rows}}
"""
    result = run_arrow_script(code, table)
    assert result["ok"] is True, result.get("error") or result
    assert result["metrics"]["rows"] == 2


def test_playground_exec_subprocess_disabled_via_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_PLAYGROUND_SUBPROCESS", "0")
    monkeypatch.setenv("OFDD_PLAYGROUND_INPROCESS", "1")
    _reload_playground()
    from openfdd_bridge.playground_exec import subprocess_enabled  # noqa: E402

    assert subprocess_enabled() is False
