"""Persisted FDD plot session descriptors (re-open Plots with the same bridge parameters)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from open_fdd.desktop.storage.paths import desktop_data_dir


def plot_shares_root() -> Path:
    root = desktop_data_dir() / "plot_shares"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_plot_share(payload: dict[str, Any]) -> str:
    """Write ``payload`` under a new UUID file; returns share id."""
    share_id = str(uuid.uuid4())
    path = plot_shares_root() / f"{share_id}.json"
    record: dict[str, Any] = {
        "version": 1,
        "id": share_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return share_id


def load_plot_share(share_id: str) -> dict[str, Any] | None:
    """Load share JSON; returns ``None`` if missing or corrupt."""
    raw = str(share_id or "").strip()
    try:
        uuid.UUID(raw)
    except ValueError:
        return None
    path = plot_shares_root() / f"{raw}.json"
    if not path.is_file():
        return None
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None
