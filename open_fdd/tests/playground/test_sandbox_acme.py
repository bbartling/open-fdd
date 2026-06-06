import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.backend import run_arrow_rule

RULES_DIR = Path(__file__).resolve().parents[3] / "workspace" / "data" / "rules_py"


def _load_rule_module(name: str):
    path = RULES_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _synthetic_zone_table(n: int = 70, *, temp: float = 70.0, last_temp: float | None = None) -> pa.Table:
    temps = [temp] * n
    if last_temp is not None:
        temps[-1] = last_temp
    return pa.table(
        {
            "timestamp": pa.array([f"2024-01-01T12:{i:02d}:00Z" for i in range(n)]),
            "zone_t": pa.array(temps, type=pa.float64()),
            "temp": pa.array(temps, type=pa.float64()),
            "value_kind": pa.array(["temp"] * n),
            "value_column": pa.array(["zone_t"] * n),
        }
    )


def test_acme_zone_oob_arrow_flags_high_temp():
    src = (RULES_DIR / "acme_zone_temp_out_of_bounds.py").read_text()
    table = _synthetic_zone_table(5, temp=72.0, last_temp=90.0)
    cfg = {"bounds_low": 65, "bounds_high": 80, "value_column": "zone_t"}
    result = run_arrow_rule(src, table, cfg)
    assert not result.errors
    assert result.true_count >= 1


def test_acme_flatline_arrow_imports_cookbook():
    mod = _load_rule_module("acme_zone_temp_flatline_1h")
    assert hasattr(mod, "apply_faults_arrow")
    table = _synthetic_zone_table()
    cfg = {"flatline_tolerance": 0.5, "value_column": "zone_t"}
    mask = mod.apply_faults_arrow(table, cfg)
    assert len(mask) == table.num_rows


def test_sweep_acme_oob_rejects_legacy_evaluate():
    from open_fdd.playground.sandbox import lint_python

    bad = "def evaluate(row, cfg):\n    return True\n"
    lint = lint_python(bad)
    assert lint["ok"] is False
