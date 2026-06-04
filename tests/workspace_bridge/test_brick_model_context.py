from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.brick_model_context import (  # noqa: E402
    catalog_entries_for_codes,
    link_faults_to_brick,
)
from openfdd_bridge.fault_catalog import is_valid_code  # noqa: E402


def test_catalog_entries_for_active_code():
    entries = catalog_entries_for_codes(["VAV-C"])
    assert entries
    assert entries[0]["code"] == "VAV-C"
    assert entries[0]["description"]
    assert entries[0]["suggested_checks"]


def test_link_faults_to_brick_equipment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    model = {
        "sites": [{"id": "demo", "name": "Demo"}],
        "equipment": [{"id": "vav-1", "site_id": "demo", "name": "VAV-1", "equipment_type": "VAV"}],
        "points": [],
    }
    (data / "model.json").write_text(json.dumps(model), encoding="utf-8")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    linked = link_faults_to_brick(
        [{"code": "VAV-C", "title": "Zone OOB", "equipment_id": "vav-1", "severity": "warning"}],
        site_id="demo",
    )
    assert linked[0]["equipment_name"] == "VAV-1"


def test_building_insight_context_has_fault_catalog(monkeypatch: pytest.MonkeyPatch):
    import openfdd_bridge.building_insight as mod

    ctx = mod._compact_context(
        {
            "alerts": [{"code": "VAV-C", "title": "Zone temp", "severity": "warning"}],
            "status": "warning",
            "traffic": "yellow",
        },
        {"summary_sentence": "zones ok"},
        {"summary_sentence": "poll ok"},
    )
    parsed = json.loads(ctx)
    assert parsed.get("fault_catalog")
    assert parsed["fault_catalog"][0]["code"] == "VAV-C"
    assert "brick_model" in parsed
    assert "api_query_guide" in parsed
