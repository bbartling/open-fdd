"""Benserver bench contract — dual driver devices, agnostic FDD rules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.bench_contract import (  # noqa: E402
    AGNOSTIC_RULE_IDS,
    BACNET_DEVICE_ID,
    NIAGARA_DEVICE_ID,
    dual_driver_devices,
    rule_bindings_span_both_sources,
    rule_is_source_agnostic,
    rules_source_agnostic,
    validate_bench_contract,
)

BENCH_MODEL = REPO / "workspace" / "data" / "bench_dual_source_model.json"


def _bench_model() -> dict:
    return json.loads(BENCH_MODEL.read_text(encoding="utf-8"))


def _bench_rules() -> list[dict]:
    return [
        {
            "id": "temp-out-of-bounds",
            "name": "Temperature out of bounds",
            "short_description": "Temperature reading is outside the configured range.",
            "enabled": True,
            "bindings": {
                "point_ids": [
                    "5007-analog-input-1173",
                    "5007-analog-input-1192",
                    "5007-analog-input-10014",
                    "niagara-bench9065-f4c0862bb4",
                    "niagara-bench9065-9fc449ad9c",
                    "niagara-bench9065-fa1b48f7f0",
                ],
            },
        },
        {
            "id": "temp-rate-of-change",
            "name": "Temperature rate of change",
            "short_description": "Temperature is changing faster than the last hour of data typically allows.",
            "enabled": True,
            "bindings": {"point_ids": ["5007-analog-input-1173", "niagara-bench9065-f4c0862bb4"]},
        },
        {
            "id": "humidity-out-of-bounds",
            "name": "Humidity out of bounds",
            "short_description": "Humidity reading is outside the configured range.",
            "enabled": True,
            "bindings": {"point_ids": ["5007-analog-input-1168", "niagara-bench9065-954f1fe9a8"]},
        },
        {
            "id": "humidity-rate-of-change",
            "name": "Humidity rate of change",
            "short_description": "Humidity is changing faster than the last hour of data typically allows.",
            "enabled": True,
            "bindings": {"point_ids": ["5007-analog-input-1168", "niagara-bench9065-954f1fe9a8"]},
        },
    ]


def test_bench_model_has_two_separate_driver_devices():
    report = dual_driver_devices(_bench_model())
    assert report["ok"] is True
    assert BACNET_DEVICE_ID in report["devices"]
    assert NIAGARA_DEVICE_ID in report["devices"]
    assert report["devices"][BACNET_DEVICE_ID]["name"] == "BACnet MS/TP device 5007"
    assert report["devices"][NIAGARA_DEVICE_ID]["name"] == "Niagara station bench9065"
    assert report["bacnet_point_count"] >= 4
    assert report["niagara_point_count"] >= 4


def test_bench_rules_are_source_agnostic():
    report = rules_source_agnostic(_bench_rules())
    assert report["ok"] is True
    assert report["has_four_bench_rules"] is True
    assert set(report["rule_ids"]) == set(AGNOSTIC_RULE_IDS)


def test_legacy_niagara_named_rules_fail_agnostic_check():
    assert rule_is_source_agnostic({"name": "Niagara Bench OA-T flatline 1h"}) is False
    assert rule_is_source_agnostic({"name": "Temperature out of bounds", "short_description": "Outside range."}) is True


def test_temp_rule_bindings_span_bacnet_and_niagara():
    model = _bench_model()
    rule = next(r for r in _bench_rules() if r["id"] == "temp-out-of-bounds")
    span = rule_bindings_span_both_sources(rule, model)
    assert span["spans_bacnet"] is True
    assert span["spans_niagara"] is True
    assert span["spans_both"] is True


def test_validate_bench_contract_passes_with_fixture_rules():
    out = validate_bench_contract(_bench_model(), _bench_rules())
    assert out["ok"] is True, out["issues"]
    assert out["temp_rules_dual_source"] is True
    assert out["humidity_rules_dual_source"] is True


def test_rules_by_data_source_preset_offline(monkeypatch, tmp_path):
    from openfdd_bridge.fdd_query_presets import run_fdd_preset

    model = _bench_model()
    rules_doc = {"version": 1, "rules": _bench_rules()}
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "rules_store.json").write_text(json.dumps(rules_doc), encoding="utf-8")
    (data / "model.json").write_text(json.dumps(model), encoding="utf-8")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))

    import openfdd_bridge.fdd_equipment as fe

    fe._RULE_STORE_CACHE = None

    out = run_fdd_preset("rules_by_data_source")
    rows = out.get("rows") or []
    sources = {str(r.get("data_source") or "") for r in rows}
    assert any("5007" in s for s in sources)
    assert any("bench9065" in s for s in sources)
    assert set(AGNOSTIC_RULE_IDS) <= {str(r.get("rule_id") or "") for r in rows}
