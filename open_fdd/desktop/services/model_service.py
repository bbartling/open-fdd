from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterator

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

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        model = self.load()
        try:
            yield model
        except Exception:
            raise
        else:
            self.store.save(model)

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

    def update_equipment(self, equipment_id: str, **fields: Any) -> dict[str, Any]:
        model = self.load()
        row = _match_id(model["equipment"], equipment_id)
        if row is None:
            raise KeyError(f"Unknown equipment id: {equipment_id}")
        row.update(fields)
        self.store.save(model)
        return row

    def update_point(self, point_id: str, **fields: Any) -> dict[str, Any]:
        model = self.load()
        row = _match_id(model["points"], point_id)
        if row is None:
            raise KeyError(f"Unknown point id: {point_id}")
        row.update(fields)
        self.store.save(model)
        return row

    def delete_site(self, site_id: str) -> dict[str, int]:
        model = self.load()
        equipment_ids = {str(e["id"]) for e in model["equipment"] if str(e.get("site_id")) == str(site_id)}
        before_sites = len(model["sites"])
        before_eq = len(model["equipment"])
        before_pt = len(model["points"])
        model["sites"] = [s for s in model["sites"] if str(s.get("id")) != str(site_id)]
        model["equipment"] = [e for e in model["equipment"] if str(e.get("site_id")) != str(site_id)]
        model["points"] = [
            p
            for p in model["points"]
            if str(p.get("site_id")) != str(site_id) and str(p.get("equipment_id") or "") not in equipment_ids
        ]
        self.store.save(model)
        return {
            "sites_deleted": before_sites - len(model["sites"]),
            "equipment_deleted": before_eq - len(model["equipment"]),
            "points_deleted": before_pt - len(model["points"]),
        }

    def delete_point(self, point_id: str) -> int:
        model = self.load()
        before = len(model["points"])
        model["points"] = [p for p in model["points"] if str(p.get("id")) != str(point_id)]
        self.store.save(model)
        return before - len(model["points"])

    def export_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        model = self.load()
        target.write_text(json.dumps(model, indent=2), encoding="utf-8")
        return target

    def import_json(self, payload: dict[str, Any], *, replace: bool = True) -> dict[str, int]:
        normalized = {
            "sites": payload.get("sites", []) if isinstance(payload.get("sites"), list) else [],
            "equipment": payload.get("equipment", []) if isinstance(payload.get("equipment"), list) else [],
            "points": payload.get("points", []) if isinstance(payload.get("points"), list) else [],
        }
        if replace:
            self.store.save(normalized)
            return {
                "sites": len(normalized["sites"]),
                "equipment": len(normalized["equipment"]),
                "points": len(normalized["points"]),
            }

        model = self.load()
        model["sites"].extend(normalized["sites"])
        model["equipment"].extend(normalized["equipment"])
        model["points"].extend(normalized["points"])
        self.store.save(model)
        return {
            "sites": len(normalized["sites"]),
            "equipment": len(normalized["equipment"]),
            "points": len(normalized["points"]),
        }

