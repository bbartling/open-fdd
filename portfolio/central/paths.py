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
    cfg = config_dir() / "sites.json"
    if cfg.is_file():
        return cfg
    legacy = portfolio_root() / "sites.json"
    if legacy.is_file():
        return legacy
    return cfg


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def reports_dir() -> Path:
    path = data_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def central_api_url() -> str:
    return os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")
