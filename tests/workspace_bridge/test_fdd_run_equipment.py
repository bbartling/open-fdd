"""FDD run equipment enrichment tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.fdd_equipment import enrich_fdd_run_with_equipment  # noqa: E402


def test_enrich_fdd_run_uses_fault_code_when_columns_empty():
    model = {"sites": [{"id": "acme"}], "equipment": [], "points": []}
    run = {"site_id": "acme", "fault_code": "AHU-C", "flagged": 1, "analytics": {}}
    out = enrich_fdd_run_with_equipment(run, model, "acme")
    assert out["equipment_names"] == ["AHU-C"]
    assert out["equipment_name"] == "AHU-C"


def test_save_results_persists_equipment_names(tmp_path, monkeypatch):
    import openfdd_bridge.fdd_results as mod

    model = {
        "sites": [{"id": "acme"}],
        "equipment": [{"id": "ahu-c", "name": "AHU-C", "site_id": "acme"}],
        "points": [],
    }

    monkeypatch.setattr(mod, "fdd_results_path", lambda: tmp_path / "fdd_results.json")
    monkeypatch.setattr(mod, "_model_for_fdd", lambda: model)
    out = mod.save_results(
        [
            {
                "rule_id": "acme-sat-flatline-1h",
                "rule_name": "SAT flatline",
                "site_id": "acme",
                "flagged": 1,
                "fault_code": "AHU-C",
            }
        ]
    )
    assert out["runs"][0]["equipment_names"] == ["AHU-C"]
    assert (tmp_path / "fdd_results.json").is_file()
