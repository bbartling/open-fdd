"""Agent → Streamlit bootstrap bridge (no HTTP API).

After a headless ``agent_afdd`` / ``export_agent_bundle`` run, write a small JSON
pointer so the next Streamlit start can auto-load the same package + dialed-in
fault settings. Browser session_state is filled from this file — agents never
need to click Streamlit.

Resolve order:
1. ``VIBE19_BOOTSTRAP`` env (file path)
2. ``vibe_code_apps_19/.last_agent_session.json`` (default write target)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BOOTSTRAP_SCHEMA = "openfdd_bootstrap_v1"
DEFAULT_BOOTSTRAP_NAME = ".last_agent_session.json"


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_bootstrap_path() -> Path:
    return app_root() / DEFAULT_BOOTSTRAP_NAME


def resolve_bootstrap_path() -> Path | None:
    """Return bootstrap file to apply, or None if missing."""
    env = (os.environ.get("VIBE19_BOOTSTRAP") or "").strip()
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    p = default_bootstrap_path()
    return p if p.is_file() else None


def build_bootstrap_payload(
    *,
    package_path: str | Path | None = None,
    building_folder: str | Path | None = None,
    session_config: dict[str, Any] | None = None,
    fault_settings_path: str | Path | None = None,
    column_map_path: str | Path | None = None,
    out_dir: str | Path | None = None,
    auto_run_rules: bool = True,
    notes: str = "",
) -> dict[str, Any]:
    if not package_path and not building_folder:
        raise ValueError("bootstrap requires package_path or building_folder")
    payload: dict[str, Any] = {
        "schema_version": BOOTSTRAP_SCHEMA,
        "package_path": str(Path(package_path).resolve()) if package_path else None,
        "building_folder": str(Path(building_folder).resolve()) if building_folder else None,
        "session_config": session_config or {},
        "fault_settings_path": str(Path(fault_settings_path).resolve()) if fault_settings_path else None,
        "column_map_path": str(Path(column_map_path).resolve()) if column_map_path else None,
        "out_dir": str(Path(out_dir).resolve()) if out_dir else None,
        "auto_run_rules": bool(auto_run_rules),
        "notes": notes or "Written by agent AFDD export for Streamlit auto-load",
    }
    return payload


def write_bootstrap(
    payload: dict[str, Any],
    *,
    path: str | Path | None = None,
    also_default: bool = True,
) -> list[Path]:
    """Write bootstrap JSON; always optionally mirror to ``.last_agent_session.json``."""
    if payload.get("schema_version") != BOOTSTRAP_SCHEMA:
        payload = {**payload, "schema_version": BOOTSTRAP_SCHEMA}
    written: list[Path] = []
    targets: list[Path] = []
    if path is not None:
        targets.append(Path(path))
    if also_default:
        targets.append(default_bootstrap_path())
    # de-dupe
    seen: set[str] = set()
    for t in targets:
        key = str(t.resolve())
        if key in seen:
            continue
        seen.add(key)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(t)
    return written


def read_bootstrap(path: str | Path | None = None) -> dict[str, Any] | None:
    p = Path(path) if path else resolve_bootstrap_path()
    if p is None or not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Bootstrap must be a JSON object: {p}")
    ver = data.get("schema_version")
    if ver not in {BOOTSTRAP_SCHEMA, "v1"}:
        raise ValueError(f"Unsupported bootstrap schema_version {ver!r} in {p}")
    data["schema_version"] = BOOTSTRAP_SCHEMA
    return data
