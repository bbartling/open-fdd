"""Persist BRICK data model as model.json under workspace/data."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import data_dir, model_json_path

_log = logging.getLogger(__name__)


def _fallback_model_paths() -> list[Path]:
    paths: list[Path] = []
    raw = os.environ.get("OFDD_MODEL_JSON_FALLBACK", "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = data_dir() / p
        paths.append(p.resolve())
    paths.append(data_dir() / "bench_dual_source_model.json")
    return paths


def _normalize_model(loaded: Any, default_model: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        return default_model
    out: dict[str, Any] = dict(loaded)
    for key in ("sites", "equipment", "points"):
        if not isinstance(out.get(key), list):
            out[key] = []
    return out


@dataclass
class ModelStore:
    path: Path = field(default_factory=model_json_path)

    def _load_fallback_or_default(self, default_model: dict[str, Any]) -> dict[str, Any]:
        for fallback in _fallback_model_paths():
            if fallback == self.path.resolve() or not fallback.is_file():
                continue
            try:
                loaded = json.loads(fallback.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                _log.warning("Cannot read fallback model at %s: %s", fallback, exc)
                continue
            _log.warning("Using fallback BRICK model from %s", fallback)
            return _normalize_model(loaded, default_model)
        return default_model

    def load(self) -> dict[str, Any]:
        default_model = {"sites": [], "equipment": [], "points": []}
        if not self.path.is_file():
            return self._load_fallback_or_default(default_model)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except PermissionError as exc:
            _log.warning("Cannot read model at %s: %s", self.path, exc)
            return self._load_fallback_or_default(default_model)
        except OSError as exc:
            if getattr(exc, "errno", None) == 13:
                _log.warning("Cannot read model at %s: %s", self.path, exc)
                return self._load_fallback_or_default(default_model)
            raise
        except json.JSONDecodeError as exc:
            _log.warning("Invalid model JSON at %s: %s", self.path, exc)
            return default_model
        return _normalize_model(loaded, default_model)

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
