from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from open_fdd.desktop.storage.model_store import ModelStore


def _match_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for row in items:
        if str(row.get("id")) == str(item_id):
            return row
    return None


@dataclass
class ModelService:
    store: ModelStore = field(default_factory=ModelStore)

    def load(self) -> dict[str, Any]:
        return self.store.load()

    def create_site(self, name: str) -> dict[str, Any]:
        model = self.load()
        row = {"id": self.store.id_str(), "name": name}
        model["sites"].append(row)
        self.store.save(model)
        return row

    def create_equipment(self, *, site_id: str, name: str, equipment_type: str) -> dict[str, Any]:
        model = self.load()
        row = {
            "id": self.store.id_str(),
            "site_id": site_id,
            "name": name,
            "equipment_type": equipment_type,
            "metadata": {},
        }
        model["equipment"].append(row)
        self.store.save(model)
        return row

    def create_point(
        self,
        *,
        site_id: str,
        equipment_id: str | None,
        external_id: str,
        brick_type: str,
        fdd_input: str | None = None,
        unit: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        model = self.load()
        row = {
            "id": self.store.id_str(),
            "site_id": site_id,
            "equipment_id": equipment_id,
            "external_id": external_id,
            "brick_type": brick_type,
            "fdd_input": fdd_input,
            "unit": unit,
            "metadata": metadata or {},
        }
        model["points"].append(row)
        self.store.save(model)
        return row

    def delete_device(self, equipment_id: str) -> dict[str, int]:
        model = self.load()
        before_eq = len(model["equipment"])
        before_pt = len(model["points"])
        model["equipment"] = [e for e in model["equipment"] if str(e.get("id")) != str(equipment_id)]
        model["points"] = [p for p in model["points"] if str(p.get("equipment_id")) != str(equipment_id)]
        self.store.save(model)
        return {"equipment_deleted": before_eq - len(model["equipment"]), "points_deleted": before_pt - len(model["points"])}

    def update_site(self, site_id: str, **fields: Any) -> dict[str, Any]:
        model = self.load()
        row = _match_id(model["sites"], site_id)
        if row is None:
            raise KeyError(f"Unknown site id: {site_id}")
        row.update(fields)
        self.store.save(model)
        return row

