"""CRUD helpers for sites / equipment / points in model.json."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import tempfile
from dataclasses import dataclass, field
import threading
from pathlib import Path
from typing import Any, Iterator

from .model_store import ModelStore

_MODEL_LOCK = threading.RLock()


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
        with _MODEL_LOCK:
            model = self.load()
            try:
                yield model
            except Exception:
                raise
            else:
                self.store.save(model)

    def export_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        model = self.load()
        payload = json.dumps(model, indent=2)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, mode="w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        return target

    def normalize_import_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .model_point_utils import enrich_point_runtime_fields

        sites = payload.get("sites", []) if isinstance(payload.get("sites"), list) else []
        equipment = payload.get("equipment", []) if isinstance(payload.get("equipment"), list) else []
        raw_points = payload.get("points", []) if isinstance(payload.get("points"), list) else []
        skeleton = {"sites": sites, "equipment": equipment, "points": raw_points, "site_id": payload.get("site_id")}
        points = [
            enrich_point_runtime_fields(pt, skeleton)
            for pt in raw_points
            if isinstance(pt, dict)
        ]
        return {"sites": sites, "equipment": equipment, "points": points}

    def import_json(self, payload: dict[str, Any], *, replace: bool = True) -> dict[str, int]:
        normalized = self.normalize_import_payload(payload)
        if replace:
            with self.transaction() as model:
                model["sites"] = list(normalized["sites"])
                model["equipment"] = list(normalized["equipment"])
                model["points"] = list(normalized["points"])
            return {
                "sites": len(normalized["sites"]),
                "equipment": len(normalized["equipment"]),
                "points": len(normalized["points"]),
            }

        with self.transaction() as model:
            for key in ("sites", "equipment", "points"):
                if not isinstance(model.get(key), list):
                    model[key] = []
            model["sites"].extend(normalized["sites"])
            model["equipment"].extend(normalized["equipment"])
            model["points"].extend(normalized["points"])
        return {
            "sites": len(normalized["sites"]),
            "equipment": len(normalized["equipment"]),
            "points": len(normalized["points"]),
        }

    def delete_point(self, point_id: str) -> dict[str, Any] | None:
        """Remove one point row; returns the removed row or None."""
        pid = str(point_id or "").strip()
        if not pid:
            return None
        removed: dict[str, Any] | None = None
        with self.transaction() as model:
            points = model.get("points") if isinstance(model.get("points"), list) else []
            kept: list[dict[str, Any]] = []
            for row in points:
                if not isinstance(row, dict):
                    continue
                if str(row.get("id") or "") == pid:
                    removed = row
                else:
                    kept.append(row)
            if removed is None:
                return None
            model["points"] = kept
        return removed

    def delete_equipment(self, equipment_id: str, *, cascade_points: bool = True) -> dict[str, int]:
        """Remove equipment; optionally drop points that reference it."""
        eq_id = str(equipment_id or "").strip()
        if not eq_id:
            return {"equipment_removed": 0, "points_removed": 0}
        eq_removed = 0
        pts_removed = 0
        with self.transaction() as model:
            equipment = model.get("equipment") if isinstance(model.get("equipment"), list) else []
            before_eq = len(equipment)
            model["equipment"] = [
                e for e in equipment if isinstance(e, dict) and str(e.get("id") or "") != eq_id
            ]
            eq_removed = before_eq - len(model["equipment"])
            if cascade_points:
                points = model.get("points") if isinstance(model.get("points"), list) else []
                before_pts = len(points)
                model["points"] = [
                    p
                    for p in points
                    if isinstance(p, dict) and str(p.get("equipment_id") or "") != eq_id
                ]
                pts_removed = before_pts - len(model["points"])
        return {"equipment_removed": eq_removed, "points_removed": pts_removed}
