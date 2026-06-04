import importlib.util
from pathlib import Path

from open_fdd.playground.sandbox import compile_evaluate, sweep_rule

RULES_DIR = Path(__file__).resolve().parents[3] / "workspace" / "data" / "rules_py"


def _load_rule_module(name: str):
    path = RULES_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _synthetic_flatline_rows(n: int = 70) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append(
            {
                "row": i,
                "ts_ms": 1_700_000_000_000 + i * 60_000,
                "ts": "2024-01-01 12:00:00",
                "temp": 70.0,
                "temp_rolling_avg": 70.0,
                "value_kind": "temp",
                "value_column": "zone_t",
            }
        )
    return rows


def test_acme_zone_oob_compiles_and_sweeps():
    src = (RULES_DIR / "acme_zone_temp_out_of_bounds.py").read_text()
    evaluate = compile_evaluate(src)
    rows = _synthetic_flatline_rows(3)
    rows[-1]["temp_rolling_avg"] = 90.0
    cfg = {"bounds_low": 65, "bounds_high": 80}
    assert evaluate(rows[-1], cfg, prev_row=rows[-2], rows=rows) is True


def test_acme_flatline_imports_from_pypi_cookbook():
    mod = _load_rule_module("acme_zone_temp_flatline_1h")
    rows = _synthetic_flatline_rows()
    cfg = {"flatline_tolerance": 0.5}
    hit = mod.evaluate(rows[-1], cfg, prev_row=rows[-2], rows=rows)
    assert hit[0] is True


def test_sweep_acme_oob_rule():
    src = (RULES_DIR / "acme_zone_temp_out_of_bounds.py").read_text()
    rows = _synthetic_flatline_rows(5)
    rows[4]["temp_rolling_avg"] = 90.0
    flags, events = sweep_rule(src, {"bounds_low": 65, "bounds_high": 80}, rows, capture_print=False)
    assert any(flags)
    assert not any(e.get("type") == "error" for e in events)
