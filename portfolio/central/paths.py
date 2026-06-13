"""Configurable paths for OpenFDD RCx Central (Docker volume friendly)."""

from __future__ import annotations

import os
from pathlib import Path


def portfolio_root() -> Path:
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    raw = os.environ.get("OPENFDD_RCX_CENTRAL_DATA")
    path = Path(raw) if raw else portfolio_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    raw = os.environ.get("OPENFDD_RCX_CENTRAL_CONFIG")
    path = Path(raw) if raw else portfolio_root() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sites_path() -> Path:
    """Prefer config/sites.json when it has entries; else portfolio/sites.json."""
    cfg = config_dir() / "sites.json"
    legacy = portfolio_root() / "sites.json"

    def _has_sites(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
            sites = raw.get("sites") if isinstance(raw, dict) else raw
            return isinstance(sites, list) and len(sites) > 0
        except Exception:
            return False

    if _has_sites(cfg):
        return cfg
    if _has_sites(legacy):
        return legacy
    return cfg if cfg.is_file() else legacy


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def reports_dir() -> Path:
    path = data_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def site_model_dir(site_id: str) -> Path:
    """Per-site BRICK model mirror (TTL + manifest) for local SPARQL."""
    path = data_dir() / "sites" / site_id / "model"
    path.mkdir(parents=True, exist_ok=True)
    return path


def site_ttl_path(site_id: str) -> Path:
    return site_model_dir(site_id) / "data_model.ttl"


def site_ttl_manifest_path(site_id: str) -> Path:
    return site_model_dir(site_id) / "ttl_manifest.json"


def central_api_url() -> str:
    return os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")
