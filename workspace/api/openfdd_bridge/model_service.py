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


def _match_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for row in items:
        if str(row.get("id")) == str(item_id):
            return row
    return None


@dataclass
class ModelService:
    store: ModelStore = field(default_factory=ModelStore)
    _mutation_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def load(self) -> dict[str, Any]:
        return self.store.load()

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        with self._mutation_lock:
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
