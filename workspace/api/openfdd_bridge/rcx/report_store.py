"""Persist generated RCx DOCX reports under workspace/reports/rcx."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import data_dir, rcx_reports_dir, repo_root, reports_root

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_MIGRATED_MARKER = ".legacy_rcx_migrated"


def reports_dir() -> Path:
    """RCx DOCX directory (workspace/reports/rcx)."""
    path = rcx_reports_dir()
    path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_reports_once(path)
    return path


def _migrate_legacy_reports_once(dest: Path) -> None:
    marker = reports_root() / _MIGRATED_MARKER
    if marker.is_file():
        return

    legacy_dirs = [
        data_dir() / "reports" / "rcx",
        repo_root() / "reports",
    ]
    for src in legacy_dirs:
        if not src.is_dir() or src.resolve() == dest.resolve():
            continue
        for path in src.glob("*.docx"):
            try:
                target = dest / path.name
                if target.is_file():
                    continue
                shutil.move(str(path), str(target))
            except OSError:
                continue

    artifacts = reports_root() / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    root_reports = repo_root() / "reports"
    if root_reports.is_dir() and root_reports.resolve() != reports_root().resolve():
        for path in root_reports.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() == ".docx":
                continue
            try:
                target = artifacts / path.name
                if target.is_file():
                    continue
                shutil.move(str(path), str(target))
            except OSError:
                continue

    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


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
                "download_path": f"/api/reports/rcx/download/{path.name}",
                "preview_path": f"/api/reports/rcx/preview/{path.name}",
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


def delete_report(filename: str) -> bool:
    path = resolve_report(filename)
    path.unlink()
    return True
