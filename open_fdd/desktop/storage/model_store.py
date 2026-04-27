from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_fdd.desktop.storage.paths import model_json_path


@dataclass
class ModelStore:
    path: Path = field(default_factory=model_json_path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sites": [], "equipment": [], "points": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, model: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(model, indent=2), encoding="utf-8")

    @staticmethod
    def id_str() -> str:
        return str(uuid.uuid4())

