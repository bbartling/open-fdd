"""Lab-only Niagara station passwords (gitignored JSON). Env vars remain preferred for production."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .paths import data_dir

_SECRETS_PATH = data_dir() / "niagara" / "station_secrets.json"


def _load() -> dict[str, str]:
    if not _SECRETS_PATH.is_file():
        return {}
    try:
        raw = json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}


def _save(secrets: dict[str, str]) -> None:
    _SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRETS_PATH.write_text(json.dumps(secrets, indent=2), encoding="utf-8")
    try:
        os.chmod(_SECRETS_PATH, 0o600)
    except OSError:
        pass


def store_password(*, station_id: str, env_name: str, password: str) -> None:
    text = (password or "").strip()
    if not text:
        return
    secrets = _load()
    if env_name:
        secrets[env_name] = text
    if station_id:
        secrets[f"station:{station_id}"] = text
    _save(secrets)


def resolve_stored_password(station: dict) -> str:
    env_name = str(station.get("password_env") or "OPENFDD_NIAGARA_ADMIN_PASSWORD").strip()
    sid = str(station.get("id") or "").strip()
    secrets = _load()
    if env_name and secrets.get(env_name):
        return secrets[env_name]
    if sid and secrets.get(f"station:{sid}"):
        return secrets[f"station:{sid}"]
    return ""
