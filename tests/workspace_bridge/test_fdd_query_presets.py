from workspace.api.openfdd_bridge.equipment_classify import hvac_bucket
from workspace.api.openfdd_bridge.fdd_query_presets import run_fdd_preset
from workspace.api.openfdd_bridge.ttl_service import _brick_equipment_class


def test_ahus_vavs_zones_counts_brick_type(monkeypatch, tmp_path):
    model = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [
            {"id": "ahu-1", "site_id": "acme", "name": "AHU 01", "brick_type": "AHU"},
            {"id": "vav-1", "site_id": "acme", "name": "Vav 01", "brick_type": "VAV"},
        ],
        "points": [
            {"id": "p1", "equipment_id": "ahu-1", "brick_type": "Supply_Air_Temperature_Sensor"},
            {"id": "p2", "equipment_id": "vav-1", "brick_type": "Zone_Air_Temperature_Sensor"},
        ],
    }

    class FakeModelService:
        def load(self):
            return model

    class FakeRuleStore:
        def list_rules(self):
            return []

    monkeypatch.setattr("workspace.api.openfdd_bridge.fdd_query_presets.ModelService", FakeModelService)
    monkeypatch.setattr("workspace.api.openfdd_bridge.fdd_query_presets.RuleStore", FakeRuleStore)
    monkeypatch.setattr("workspace.api.openfdd_bridge.fdd_query_presets.ensure_default_site", lambda *a, **k: "acme")

    out = run_fdd_preset("ahus_vavs_zones", site_id="acme")
    classes = {row["hvac_class"] for row in out["rows"]}
    assert classes == {"AHU", "VAV"}


def test_brick_equipment_class_maps_ahu():
    assert _brick_equipment_class({"brick_type": "AHU", "name": "AHU 01"}) == "Air_Handling_Unit"
    assert _brick_equipment_class({"brick_type": "VAV"}) == "Variable_Air_Volume_Box"
    assert hvac_bucket({"brick_type": "AHU", "name": "Rtu 01"}) == "AHU"
