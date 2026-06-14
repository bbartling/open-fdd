from __future__ import annotations

from pathlib import Path

from open_fdd.arrow_runtime.backend import lint_arrow_rule
from open_fdd.playground.sandbox import lint_python


def test_lint_rejects_pandas_import():
    code = "import pandas as pd\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return table['x']"
    lint = lint_arrow_rule(code, strict_imports=True)
    assert not lint["ok"]
    msgs = " ".join(i["message"] for i in lint["issues"])
    assert "pandas" in msgs.lower() or "forbidden" in msgs.lower()
    assert "PyArrow-only" in msgs


def test_lint_script_mode_rejects_df():
    code = "fan_hours = df['supply-fan'].sum()\nout = {'events': []}"
    lint = lint_python(code, require_arrow_rule=False, strict_imports=True)
    assert not lint["ok"]
    msgs = " ".join(i["message"] for i in lint["issues"])
    assert "table" in msgs.lower()
    assert "df" in msgs.lower()


def test_lint_accepts_arrow_script():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "workspace"
        / "data"
        / "rules_py"
        / "ahu_fan_and_system_run_hours.py"
    )
    text = script_path.read_text(encoding="utf-8")
    lint = lint_python(text, require_arrow_rule=False, strict_imports=True)
    assert lint["ok"], lint["issues"]
