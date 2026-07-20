"""Resolve HVAC CSV data root, building, and poll interval from manifest."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from shared.env_loader import load_env_files, resolve_data_path

load_env_files()

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = APP_ROOT / "data" / "hvac_systems_CLEANED"


def _load_paths_file() -> dict:
    for name in (
        "data_paths.local.json",
        "data_paths.json",
        "data_paths.local.yaml",
        "data_paths.yaml",
    ):
        path = APP_ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text) or {}
        try:
            import yaml  # type: ignore

            return yaml.safe_load(text) or {}
        except ImportError:
            raise RuntimeError(
                f"Install PyYAML to use {path.name}, or use data_paths.local.json instead"
            ) from None
    return {}


@lru_cache(maxsize=1)
def get_config() -> "DataConfig":
    return DataConfig.load()


class DataConfig:
    def __init__(
        self,
        data_root: Path,
        building: str = "BUILDING_100",
        weather_subdir: str = "weather",
    ) -> None:
        self.data_root = Path(data_root)
        self.building = building
        self.weather_subdir = weather_subdir

    @classmethod
    def load(cls) -> DataConfig:
        paths = _load_paths_file()
        root = os.environ.get("HVAC_DATA_ROOT") or paths.get("data_root")
        if root:
            data_root = resolve_data_path(root)
        elif DEFAULT_DATA_ROOT.is_dir():
            data_root = DEFAULT_DATA_ROOT.resolve()
        else:
            data_root = DEFAULT_DATA_ROOT

        building = os.environ.get("HVAC_BUILDING", paths.get("building", "BUILDING_100"))
        if not building:
            building = cls._auto_building(data_root) or "BUILDING_100"
        weather = os.environ.get("HVAC_WEATHER_SUBDIR", paths.get("weather_subdir", "weather"))
        return cls(data_root=Path(data_root), building=building, weather_subdir=weather)

    @staticmethod
    def _auto_building(data_root: Path) -> str | None:
        """Pick first BUILDING_* folder with manifest.json when HVAC_BUILDING unset."""
        if not data_root.is_dir():
            return None
        candidates = sorted(
            d.name
            for d in data_root.iterdir()
            if d.is_dir() and d.name.upper().startswith("BUILDING") and (d / "manifest.json").is_file()
        )
        return candidates[0] if candidates else None

    def site_label(self) -> str:
        """Display name derived from building folder id (no customer branding)."""
        return self.building.replace("_", " ").title()

    def site_timezone(self) -> str:
        """IANA timezone from manifest or HVAC_TIMEZONE env (default UTC)."""
        if self.manifest_path.is_file():
            meta = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            tz = meta.get("timezone")
            if tz:
                return str(tz)
        return os.environ.get("HVAC_TIMEZONE", "UTC")

    @property
    def building_dir(self) -> Path:
        return self.data_root / self.building

    @property
    def weather_dir(self) -> Path:
        return self.data_root / self.weather_subdir

    @property
    def manifest_path(self) -> Path:
        return self.building_dir / "manifest.json"

    def poll_seconds(self, building: str | None = None) -> int:
        """Grid interval from building manifest (default 300s = 5 min)."""
        bdir = self.data_root / (building or self.building)
        manifest = bdir / "manifest.json"
        if manifest.is_file():
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            mins = float(meta.get("grid_minutes", 5))
            return max(60, int(mins * 60))
        return int(os.environ.get("HVAC_POLL_SECONDS", 300))

    def confirm_rows(self, persist_seconds: int = 300) -> int:
        return max(1, persist_seconds // self.poll_seconds())

    def vav_dir(self, building: str | None = None) -> Path:
        return self.data_root / (building or self.building) / "VAV"

    def list_vav_boxes(self, building: str | None = None) -> list[str]:
        vav = self.vav_dir(building)
        if not vav.is_dir():
            return []
        return sorted(d.name for d in vav.iterdir() if d.is_dir())
