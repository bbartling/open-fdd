from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
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


def test_subprocess_worker_runs_sweep(subprocess_playground):
    from openfdd_bridge.playground import sweep_rule  # noqa: E402

    rows = [{"SAT": 80.0, "timestamp": "2025-01-01T00:00:00Z"}]
    code = """def evaluate(row, cfg, prev_row=None, rows=None):
    return float(row.get("SAT", 0)) > float(cfg.get("high", 75))
"""
    flags, events = sweep_rule(code, {"high": 75}, rows, capture_print=False)
    assert flags == [True]
    assert any(e.get("type") == "summary" for e in events)


def test_subprocess_infinite_loop_times_out(subprocess_playground):
    from openfdd_bridge.playground import sweep_rule  # noqa: E402

    rows = [{"temp": 72.0, "timestamp": "2025-01-01T00:00:00Z"}]
    code = "def evaluate(row, cfg, prev_row=None, rows=None):\n    while True:\n        pass\n    return False\n"
    started = time.time()
    flags, events = sweep_rule(code, {}, rows, capture_print=False)
    elapsed = time.time() - started
    assert elapsed < 25.0
    assert flags == [False]
    assert any(
        "timed out" in str(e.get("text", "")).lower() or "timed out" in str(e.get("message", "")).lower()
        for e in events
    )


def test_subprocess_rejects_import_os(subprocess_playground):
    from openfdd_bridge.playground import sweep_rule  # noqa: E402

    code = "import os\ndef evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"
    flags, events = sweep_rule(code, {}, [{"x": 1}], capture_print=False)
    assert flags == [False]
    assert any(e.get("type") == "error" for e in events)


def test_subprocess_run_script(subprocess_playground, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_PLAYGROUND_TIMEOUT_S", "15")
    _reload_playground()
    from openfdd_bridge.playground import run_dataframe_script  # noqa: E402

    df = pd.DataFrame({"SAT": [70.0, 85.0]})
    code = """
df = df.copy()
df["hit"] = (df["SAT"] > 75).astype(int)
out = {"df": df, "events": []}
"""
    result = run_dataframe_script(code, df)
    assert result["ok"] is True, result.get("error") or result
    assert "hit" in result.get("columns", [])


def test_playground_exec_subprocess_disabled_via_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_PLAYGROUND_SUBPROCESS", "0")
    monkeypatch.setenv("OFDD_PLAYGROUND_INPROCESS", "1")
    _reload_playground()
    from openfdd_bridge.playground_exec import subprocess_enabled  # noqa: E402

    assert subprocess_enabled() is False
