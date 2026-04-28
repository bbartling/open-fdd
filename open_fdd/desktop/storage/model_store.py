from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_fdd.desktop.storage.paths import model_json_path


@dataclass
class ModelStore:
    path: Path = field(default_factory=model_json_path)

    def load(self) -> dict[str, Any]:
        default_model = {"sites": [], "equipment": [], "points": []}
        if not self.path.exists():
            return default_model
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return default_model
        out: dict[str, Any] = dict(loaded)
        for key in ("sites", "equipment", "points"):
            if not isinstance(out.get(key), list):
                out[key] = []
        return out

    def save(self, model: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(model, indent=2)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, mode="w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    @staticmethod
    def id_str() -> str:
        return str(uuid.uuid4())

