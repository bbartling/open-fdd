"""Persist generated RCx DOCX reports on the edge volume."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import data_dir

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def reports_dir() -> Path:
    path = data_dir() / "reports" / "rcx"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not base.lower().endswith(".docx"):
        base = f"{base}.docx"
    cleaned = _SAFE_NAME.sub("-", base).strip("-")
    return cleaned or "openfdd-rcx-edge.docx"


def save_report(filename: str, content: bytes) -> Path:
    safe = _safe_filename(filename)
    out = reports_dir() / safe
    out.write_bytes(content)
    return out


def list_reports(*, limit: int = 100) -> list[dict[str, Any]]:
    root = reports_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "saved_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def resolve_report(filename: str) -> Path:
    safe = _safe_filename(filename)
    path = reports_dir() / safe
    if not path.is_file():
        raise FileNotFoundError(safe)
    return path
