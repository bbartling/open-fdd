from __future__ import annotations

from pathlib import Path

import json

from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.model_store import ModelStore


def test_model_crud_and_delete_device(tmp_path: Path) -> None:
    store = ModelStore(path=tmp_path / "model.json")
    svc = ModelService(store=store)

    site = svc.create_site("Site A")
    eq = svc.create_equipment(site_id=site["id"], name="AHU-1", equipment_type="AHU")
    svc.create_point(
        site_id=site["id"],
        equipment_id=eq["id"],
        external_id="ahu1_sa_temp",
        brick_type="Supply_Air_Temperature_Sensor",
    )

    model = svc.load()
    assert len(model["sites"]) == 1
    assert len(model["equipment"]) == 1
    assert len(model["points"]) == 1

    removed = svc.delete_device(eq["id"])
    assert removed["equipment_deleted"] == 1
    assert removed["points_deleted"] == 1

    model2 = svc.load()
    assert model2["equipment"] == []
    assert model2["points"] == []


def test_model_export_import_json(tmp_path: Path) -> None:
    store = ModelStore(path=tmp_path / "model.json")
    svc = ModelService(store=store)
    site = svc.create_site("Site A")
    svc.create_equipment(site_id=site["id"], name="AHU-1", equipment_type="AHU")
    export_path = tmp_path / "export.json"
    out = svc.export_json(export_path)
    assert out.exists()
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert len(exported["sites"]) == 1
    fresh = ModelService(store=ModelStore(path=tmp_path / "imported.json"))
    counts = fresh.import_json(exported, replace=True)
    assert counts["sites"] == 1
    assert len(fresh.load()["equipment"]) == 1

