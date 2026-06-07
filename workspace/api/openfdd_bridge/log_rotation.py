"""Automatic audit/error log retention and size rotation (no operator action required)."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .audit import audit_log_path, error_log_path
from .paths import workspace_dir

_log = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_MAX_MB = 50


def _retention_days() -> int:
    raw = os.environ.get("OFDD_LOG_RETENTION_DAYS", "").strip()
    if not raw:
        return _DEFAULT_RETENTION_DAYS
    try:
        return max(1, min(int(raw), 3650))
    except ValueError:
        return _DEFAULT_RETENTION_DAYS


def _max_file_bytes() -> int:
    raw = os.environ.get("OFDD_LOG_MAX_MB", "").strip()
    if not raw:
        return _DEFAULT_MAX_MB * 1024 * 1024
    try:
        mb = max(1, min(int(raw), 1024))
        return mb * 1024 * 1024
    except ValueError:
        return _DEFAULT_MAX_MB * 1024 * 1024


def _parse_record_timestamp(line: str) -> datetime | None:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    ts = record.get("@timestamp") or record.get("timestamp")
    if not ts:
        return None
    try:
        if isinstance(ts, str) and ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def _prune_jsonl_by_age(path: Path, *, cutoff: datetime) -> int:
    """Drop JSONL lines older than cutoff. Returns number of lines removed."""
    if not path.is_file():
        return 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _log.warning("log rotation: cannot read %s: %s", path, exc)
        return 0
    if not lines:
        return 0
    kept: list[str] = []
    removed = 0
    for line in lines:
        if not line.strip():
            continue
        ts = _parse_record_timestamp(line)
        if ts is None:
            kept.append(line)
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            kept.append(line)
        else:
            removed += 1
    if removed:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            _log.warning("log rotation: cannot write %s: %s", path, exc)
            return 0
    return removed


def _rotate_if_oversized(path: Path) -> bool:
    """Archive oversized log to a dated sibling file. Returns True if rotated."""
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= _max_file_bytes():
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    try:
        shutil.move(str(path), str(archive))
        path.touch()
        _log.info("log rotation: archived %s (%d bytes) -> %s", path.name, size, archive.name)
        return True
    except OSError as exc:
        _log.warning("log rotation: cannot archive %s: %s", path, exc)
        return False


def _prune_local_run_logs(cutoff: datetime) -> int:
    """Remove stale stdout capture files from workspace/.local-run/."""
    run_dir = workspace_dir() / ".local-run"
    if not run_dir.is_dir():
        return 0
    removed = 0
    for path in run_dir.glob("*.log"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                _log.warning("log rotation: cannot delete %s: %s", path, exc)
    return removed


def rotate_logs_on_startup() -> dict[str, int]:
    """Prune aged JSONL audit/error logs and stale .local-run captures."""
    days = _retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stats = {"retention_days": days, "audit_pruned": 0, "error_pruned": 0, "local_run_removed": 0}
    for path, key in ((audit_log_path(), "audit_pruned"), (error_log_path(), "error_pruned")):
        _rotate_if_oversized(path)
        stats[key] = _prune_jsonl_by_age(path, cutoff=cutoff)
    stats["local_run_removed"] = _prune_local_run_logs(cutoff)
    if any(stats[k] for k in ("audit_pruned", "error_pruned", "local_run_removed")):
        _log.info("log rotation complete: %s", stats)
    return stats
