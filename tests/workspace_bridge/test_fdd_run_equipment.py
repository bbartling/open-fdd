"""FDD run equipment enrichment tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.fdd_equipment import (  # noqa: E402
    enrich_fdd_run_with_equipment,
    equipment_from_rule_bindings,
    plain_symptom_from_rule_name,
)
from openfdd_bridge import fdd_equipment as fdd_equipment_mod  # noqa: E402
from openfdd_bridge.fdd_results import _fdd_alert_title  # noqa: E402


def _use_workspace_data(monkeypatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    fdd_equipment_mod._RULE_STORE_CACHE = None


def _bench_model() -> dict:
    return json.loads((REPO / "workspace" / "data" / "model.json").read_text(encoding="utf-8"))


def test_plain_symptom_strips_niagara_prefix():
    assert plain_symptom_from_rule_name("Niagara Bench OA-T flatline 1h") == "OA-T flatline 1h"
    assert plain_symptom_from_rule_name("Bench humidity flatline 1h") == "humidity flatline 1h"


def test_equipment_from_rule_bindings_resolves_bacnet_device(monkeypatch):
    _use_workspace_data(monkeypatch)
    model = _bench_model()
    names, ids = equipment_from_rule_bindings(model, "demo", "temp-out-of-bounds")
    assert "bacnet-5007" in ids
    assert "BACnet MS/TP device 5007" in names


def test_equipment_from_rule_bindings_resolves_niagara_station(monkeypatch):
    _use_workspace_data(monkeypatch)
    model = _bench_model()
    names, ids = equipment_from_rule_bindings(model, "demo", "temp-out-of-bounds")
    assert "niagara-bench9065" in ids
    assert "Niagara station bench9065" in names


def test_enrich_fdd_run_uses_rule_bindings_not_fault_code(monkeypatch):
    _use_workspace_data(monkeypatch)
    model = _bench_model()
    run = {
        "site_id": "demo",
        "rule_id": "temp-out-of-bounds",
        "rule_name": "Temperature out of bounds",
        "short_description": "Temperature reading is outside the configured range.",
        "flagged": 1,
        "analytics": {},
    }
    out = enrich_fdd_run_with_equipment(run, model, "demo")
    assert out["equipment_names"]
    assert out["symptom"] == "Temperature reading is outside the configured range."


def test_fdd_alert_title_is_equipment_first():
    title = _fdd_alert_title(
        {
            "rule_name": "Temperature out of bounds",
            "short_description": "Temperature reading is outside the configured range.",
            "symptom": "Temperature reading is outside the configured range.",
            "site_id": "demo",
        },
        flagged=24,
        equipment_names=["Niagara station bench9065"],
    )
    assert title.startswith("Niagara station bench9065 — Temperature reading is outside the configured range.")


def test_save_results_persists_equipment_names(tmp_path, monkeypatch):
    import openfdd_bridge.fdd_results as mod

    _use_workspace_data(monkeypatch)
    model = _bench_model()

    monkeypatch.setattr(mod, "fdd_results_path", lambda: tmp_path / "fdd_results.json")
    monkeypatch.setattr(mod, "_model_for_fdd", lambda: model)
    out = mod.save_results(
        [
            {
                "rule_id": "temp-out-of-bounds",
                "rule_name": "Temperature out of bounds",
                "short_description": "Temperature reading is outside the configured range.",
                "site_id": "demo",
                "flagged": 1,
            }
        ]
    )
    assert out["runs"][0]["equipment_names"]
    assert (tmp_path / "fdd_results.json").is_file()
