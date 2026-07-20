"""App configuration — BUILDING_100 demo defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

APP_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = APP_ROOT / "configs"


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes"}


def running_in_docker() -> bool:
    """True when Dockerfile set ``VIBE19_DOCKER=1`` or the runtime has ``/.dockerenv``."""
    if _truthy_env("VIBE19_DOCKER"):
        return True
    return Path("/.dockerenv").is_file()


@dataclass
class AppConfig:
    data_root: Path
    building_id: str
    weather_subdir: str
    role_map_path: Path
    rule_defaults_path: Path
    app_mode: str  # "local" | "cloud" | "auto"

    @property
    def is_cloud(self) -> bool:
        """True when running without a usable local historian tree (Cloud / locked FS)."""
        if self.app_mode == "cloud":
            return True
        if self.app_mode == "local":
            # Docker without a mounted data root: zip-only (avoid dead Folder path UX)
            if running_in_docker() and not self.data_root.is_dir():
                return True
            return False
        # auto: cloud-like if default data root missing (typical Streamlit Community Cloud)
        return not self.data_root.is_dir()

    @property
    def allow_server_paths(self) -> bool:
        return not self.is_cloud

    @property
    def allow_disk_writes(self) -> bool:
        return not self.is_cloud

    @classmethod
    def load(cls) -> AppConfig:
        building_yaml = CONFIGS / "building_100.yaml"
        extra = {}
        if building_yaml.is_file():
            extra = yaml.safe_load(building_yaml.read_text(encoding="utf-8")) or {}
        root = os.environ.get("HVAC_DATA_ROOT") or extra.get("data_root", "./data/hvac_systems_CLEANED")
        building = os.environ.get("HVAC_BUILDING") or extra.get("building_id", "BUILDING_100")
        weather = os.environ.get("HVAC_WEATHER_SUBDIR") or extra.get("weather_subdir", "weather")
        mode = (os.environ.get("APP_MODE") or extra.get("app_mode") or "auto").strip().lower()
        if mode not in {"local", "cloud", "auto"}:
            mode = "auto"
        return cls(
            data_root=Path(root).expanduser().resolve() if Path(root).is_absolute() else (APP_ROOT / root).resolve(),
            building_id=building,
            weather_subdir=weather,
            role_map_path=CONFIGS / "role_map.yaml",
            rule_defaults_path=CONFIGS / "rule_defaults.yaml",
            app_mode=mode,
        )
