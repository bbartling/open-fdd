from __future__ import annotations

from pathlib import Path

from open_fdd.desktop.services.brick_service import BrickService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.storage.model_store import ModelStore


def test_ttl_sync_and_brick_map(tmp_path: Path) -> None:
    store = ModelStore(path=tmp_path / "model.json")
    svc = ModelService(store=store)
    site = svc.create_site("Site")
    eq = svc.create_equipment(site_id=site["id"], name="AHU", equipment_type="AHU")
    svc.create_point(
        site_id=site["id"],
        equipment_id=eq["id"],
        external_id="sa_temp",
        brick_type="Supply_Air_Temperature_Sensor",
        fdd_input="sat",
        metadata={"external_ref": "feather://csv/site/sa_temp"},
    )
    ttl_path = tmp_path / "model.ttl"
    ttl = TtlService(model_store=store, ttl_path=ttl_path)
    out = ttl.sync()
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Supply_Air_Temperature_Sensor" in text
    brick = BrickService(ttl_path=ttl_path)
    cmap = brick.resolve_column_map()
    assert cmap.get("sat") == "sa_temp"

