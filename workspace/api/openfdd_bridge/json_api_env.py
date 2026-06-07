"""Load workspace/json_api.env.local and expand ${ENV:VAR} placeholders in driver URLs."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .paths import workspace_dir

_ENV_PATTERN = re.compile(r"\$\{ENV:([A-Z0-9_]+)\}|\$\{([A-Z0-9_]+)\}")
_LOADED = False


def json_api_env_path() -> Path:
    return workspace_dir() / "json_api.env.local"


def load_json_api_env(*, reload: bool = False) -> Path | None:
    """Parse KEY=VALUE lines into os.environ (does not override existing vars)."""
    global _LOADED
    if _LOADED and not reload:
        return json_api_env_path() if json_api_env_path().is_file() else None
    path = json_api_env_path()
    if not path.is_file():
        _LOADED = True
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
    _LOADED = True
    return path


def expand_env_string(text: str) -> str:
    """Replace ${ENV:NAME} or ${NAME} with os.environ values; leave token if unset."""
    load_json_api_env()

    def _repl(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return os.environ.get(name, match.group(0))

    return _ENV_PATTERN.sub(_repl, str(text or ""))


def expand_env_mapping(values: dict[str, str]) -> dict[str, str]:
    return {str(k): expand_env_string(str(v)) for k, v in values.items()}


def env_var_configured(name: str) -> bool:
    load_json_api_env()
    return bool(str(os.environ.get(name) or "").strip())


def missing_env_vars(names: list[str]) -> list[str]:
    load_json_api_env()
    return [n for n in names if not env_var_configured(n)]
