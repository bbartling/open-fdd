"""Bench device 5007 — Arrow Rule Lab columns, bindings, and plot scoping.

MS/TP 5007 on bensserver test bench:
  oa-t / stat_zn-t — same ambient space (different BRICK labels)
  oa-h — ambient humidity (Outside_Air_Humidity_Sensor tag)
  duct-t — real duct discharge sensor on duct-1 equipment
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BENCH_MODEL = REPO / "workspace" / "data" / "bench_import_model.json"
BENCH_COLUMNS = ("oa-t", "stat_zn-t", "oa-h", "duct-t")

# Feather historian column names are hardcoded in Arrow rules as VALUE_COLUMN.
RULE_EXPECTED_COLUMN = {
    "bench-oa-t-flatline-1h": "oa-t",
    "bench-oa-t-oob": "oa-t",
    "bench-stat-zn-t-flatline-1h": "stat_zn-t",
    "duct-t-flatline-1h": "duct-t",
    "duct-t-spread-1h": "duct-t",
}


def _reload_bridge() -> None:
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]


def _bench_rules_store_path() -> Path | None:
    for path in (REPO / "workspace" / "data" / "rules_store.json",):
        if path.is_file():
            return path
    return REPO / "edge_config" / "demo" / "bens-office" / "rules_store.json"


@pytest.fixture
def bench_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))

    rules_src = _bench_rules_store_path()
    if rules_src.is_file():
        (data / "rules_store.json").write_text(rules_src.read_text(encoding="utf-8"), encoding="utf-8")
    rules_py = REPO / "workspace" / "data" / "rules_py"
    if rules_py.is_dir():
        import shutil

        shutil.copytree(rules_py, data / "rules_py", dirs_exist_ok=True)

    _reload_bridge()
    from openfdd_bridge.model_service import ModelService as MS  # noqa: E402

    model = json.loads(BENCH_MODEL.read_text(encoding="utf-8"))
    MS().import_json(model, replace=True)
    yield data


def _bench_frame(rows: int = 24) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="UTC").floor("min")
    ts = pd.date_range(end - pd.Timedelta(minutes=rows - 1), periods=rows, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "oa-t": [72.0] * rows,
            "stat_zn-t": [72.1 + (i % 3) * 0.05 for i in range(rows)],
            "oa-h": [45.0 + (i % 5) * 0.2 for i in range(rows)],
            "duct-t": [68.0 + (i % 8) * 0.3 for i in range(rows)],
        }
    )


def test_bench_model_has_four_distinct_historian_columns(bench_env: Path):
    model = json.loads(BENCH_MODEL.read_text(encoding="utf-8"))
    cols = sorted({str(p.get("external_id") or "") for p in model["points"]})
    assert cols == sorted(BENCH_COLUMNS)


def test_arrow_rules_use_hardcoded_feather_column_names(bench_env: Path):
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402
    from openfdd_bridge.rule_source import read_source  # noqa: E402

    for rule in RuleStore().list_rules():
        rid = str(rule.get("id") or "")
        expected = RULE_EXPECTED_COLUMN.get(rid)
        if not expected:
            continue
        src = read_source(str(rule.get("source_path") or "")) or str(rule.get("code") or "")
        assert f'VALUE_COLUMN = "{expected}"' in src or f"VALUE_COLUMN = '{expected}'" in src, rid


def test_each_bench_rule_runs_on_matching_column(bench_env: Path):
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402
    from openfdd_bridge.rule_source import read_source  # noqa: E402
    from open_fdd.arrow_runtime.backend import run_arrow_rule  # noqa: E402

    df = _bench_frame()
    table = pa.Table.from_pandas(df, preserve_index=False)
    for rule in RuleStore().list_rules():
        rid = str(rule.get("id") or "")
        if rid not in RULE_EXPECTED_COLUMN:
            continue
        code = read_source(str(rule.get("source_path") or "")) or str(rule.get("code") or "")
        result = run_arrow_rule(code, table, dict(rule.get("config") or {}), rule_id=rid)
        assert not result.errors, f"{rid}: {result.errors}"
        assert len(result.fault_mask) == df.shape[0]


def test_wrong_value_column_fails_at_runtime(bench_env: Path):
    from open_fdd.arrow_runtime.backend import run_arrow_rule  # noqa: E402

    bad = (
        'import pyarrow.compute as pc\n\nVALUE_COLUMN = "nonexistent-col"\n\n'
        "def apply_faults_arrow(table, cfg, context=None):\n"
        "    return pc.greater(pc.cast(table[VALUE_COLUMN], 'float64'), 0)\n"
    )
    table = pa.Table.from_pandas(_bench_frame(), preserve_index=False)
    result = run_arrow_rule(bad, table, {}, rule_id="bad-col")
    assert result.errors


def test_brick_type_binding_scopes_zone_temp_not_oa_temp(bench_env: Path):
    from openfdd_bridge.model_service import ModelService as MS  # noqa: E402
    from openfdd_bridge.plot_readings import evaluate_fault_plots  # noqa: E402
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402

    store = RuleStore()
    store.upsert(
        {
            "id": "bench-class-zn-flatline",
            "name": "Zone temp class flatline",
            "mode": "rule",
            "backend": "arrow",
            "code": store.list_rules()[0]["code"],
            "bindings": {"brick_types": ["Zone_Air_Temperature_Sensor"]},
            "enabled": True,
        },
        saved_by="test",
    )
    model = MS().load()
    df = _bench_frame()
    oa_scope, _, _ = evaluate_fault_plots(df, "demo", model, scope_columns=["oa-t"])
    zn_scope, panels_zn, _ = evaluate_fault_plots(df, "demo", model, scope_columns=["stat_zn-t"])
    assert "bench-class-zn-flatline" not in oa_scope
    assert "bench-class-zn-flatline" in zn_scope
    assert panels_zn


def test_equipment_binding_covers_bench_ambient_points(bench_env: Path):
    from openfdd_bridge.model_service import ModelService as MS  # noqa: E402
    from openfdd_bridge.plot_readings import _rule_matches_plot_scope, _plot_scope_for_columns  # noqa: E402
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402

    store = RuleStore()
    store.upsert(
        {
            "id": "bench-eq-flatline",
            "name": "Bench equipment flatline",
            "mode": "rule",
            "backend": "arrow",
            "code": store.list_rules()[0]["code"],
            "bindings": {"equipment_ids": ["bench-1"]},
            "enabled": True,
        },
        saved_by="test",
    )
    model = MS().load()
    rule = next(r for r in store.list_rules() if r.get("id") == "bench-eq-flatline")
    bricks, points, eq = _plot_scope_for_columns(model, "demo", ["oa-t", "stat_zn-t", "oa-h"])
    assert "bench-1" in eq
    assert _rule_matches_plot_scope(rule, scope_bricks=bricks, scope_point_ids=points, scope_equipment_ids=eq)
    _, points_duct, eq_duct = _plot_scope_for_columns(model, "demo", ["duct-t"])
    assert "bench-1" not in eq_duct or "duct-1" in eq_duct


def test_commissioning_import_assigns_rules_at_scale(bench_env: Path):
    from openfdd_bridge.commissioning_bundle import apply_commissioning_import  # noqa: E402
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402

    model = json.loads(BENCH_MODEL.read_text(encoding="utf-8"))
    payload = {
        "sites": model["sites"],
        "equipment": model["equipment"],
        "points": [
            {**pt, "fdd_rule_ids": ["bench-oa-t-flatline-1h"]}
            for pt in model["points"]
            if pt.get("external_id") in ("oa-t", "stat_zn-t")
        ],
        "fdd_rules": [
            {
                "id": "bench-oa-t-flatline-1h",
                "name": "Bench OA-T flatline 1h",
                "enabled": True,
                "bindings": {"point_ids": [], "equipment_ids": [], "brick_types": []},
            }
        ],
    }
    result = apply_commissioning_import(payload)
    assert result.get("fdd_rules_updated", 0) >= 1
    rule = next(r for r in RuleStore().list_rules() if r.get("id") == "bench-oa-t-flatline-1h")
    bound = set(rule["bindings"]["point_ids"])
    assert "5007-analog-input-1173" in bound
    assert "5007-analog-input-10014" in bound


def test_ai_style_rule_uses_cfg_column_override(bench_env: Path):
    from open_fdd.arrow_runtime.backend import run_arrow_rule  # noqa: E402

    code = (
        "import pyarrow.compute as pc\n\n"
        "def apply_faults_arrow(table, cfg, context=None):\n"
        "    col = str(cfg.get('value_column') or 'oa-t')\n"
        "    vals = pc.cast(table[col], 'float64')\n"
        "    return pc.greater(vals, float(cfg.get('high', 90)))\n"
    )
    df = _bench_frame()
    table = pa.Table.from_pandas(df, preserve_index=False)
    for col in ("oa-t", "stat_zn-t", "duct-t"):
        result = run_arrow_rule(code, table, {"value_column": col, "high": 200}, rule_id="cfg-col")
        assert not result.errors
        assert len(result.fault_mask) == len(df)
