"""Profile registry: required check IDs loaded from inventory (single policy source)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INVENTORY_DIR = Path(__file__).resolve().parents[1] / "inventory"
PROFILE_REQUIRED_PATH = INVENTORY_DIR / "profile_required_v1.json"
REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "profile_registry_v1.json"
)


def load_profile_required(path: Path | None = None) -> dict[str, Any]:
    p = path or PROFILE_REQUIRED_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema_version") != "openfdd_profile_required_v1":
        raise ValueError(
            f"unsupported profile_required schema_version {data.get('schema_version')!r}"
        )
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("profile_required_v1.json missing profiles")
    return profiles


def required_check_ids(profile: str, suites: list[str]) -> list[str]:
    table = load_profile_required().get(profile) or {}
    out: list[str] = []
    for s in suites:
        out.extend(table.get(s, []))
    return out


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Compatibility shim — prefer inventory/profile_required_v1.json."""
    p = path or REGISTRY_PATH
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {
        "schema_version": "openfdd_security_profiles_v1",
        "profiles": load_profile_required(),
    }
