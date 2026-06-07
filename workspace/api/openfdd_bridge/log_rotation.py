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
_DEFAULT_LOCAL_RUN_MAX_MB = 25
_DEFAULT_ROTATE_INTERVAL_HOURS = 6.0


def _retention_days() -> int:
    raw = os.environ.get("OFDD_LOG_RETENTION_DAYS", "").strip()
    if not raw:
        return _DEFAULT_RETENTION_DAYS
    try:
        return max(1, min(int(raw), 3650))
    except ValueError:
        return _DEFAULT_RETENTION_DAYS


def _max_local_run_bytes() -> int:
    raw = os.environ.get("OFDD_LOCAL_RUN_LOG_MAX_MB", "").strip()
    if not raw:
        return _DEFAULT_LOCAL_RUN_MAX_MB * 1024 * 1024
    try:
        mb = max(1, min(int(raw), 512))
        return mb * 1024 * 1024
    except ValueError:
        return _DEFAULT_LOCAL_RUN_MAX_MB * 1024 * 1024


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


def _rotate_plain_log_if_oversized(path: Path, *, max_bytes: int) -> bool:
    """Archive oversized plain-text stdout logs (run_local.sh captures)."""
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= max_bytes:
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


def _prune_local_run_logs(cutoff: datetime) -> dict[str, int]:
    """Rotate oversized and remove aged stdout capture files under workspace/.local-run/."""
    run_dir = workspace_dir() / ".local-run"
    stats = {"local_run_removed": 0, "local_run_rotated": 0}
    if not run_dir.is_dir():
        return stats
    max_bytes = _max_local_run_bytes()
    for path in sorted(run_dir.glob("*.log")):
        if _rotate_plain_log_if_oversized(path, max_bytes=max_bytes):
            stats["local_run_rotated"] += 1
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                stats["local_run_removed"] += 1
            except OSError as exc:
                _log.warning("log rotation: cannot delete %s: %s", path, exc)
    for path in sorted(run_dir.glob("*.*.log")):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                stats["local_run_removed"] += 1
            except OSError as exc:
                _log.warning("log rotation: cannot delete %s: %s", path, exc)
    return stats


def _related_archive_paths(path: Path) -> list[Path]:
    """Rotated siblings such as audit.20260101T120000Z.jsonl next to audit.jsonl."""
    pattern = f"{path.stem}.*{path.suffix}"
    return sorted(p for p in path.parent.glob(pattern) if p.is_file() and p != path)


def _prune_log_family(path: Path, *, cutoff: datetime) -> int:
    removed = 0
    for candidate in [path, *_related_archive_paths(path)]:
        removed += _prune_jsonl_by_age(candidate, cutoff=cutoff)
        if candidate != path and candidate.is_file() and candidate.stat().st_size == 0:
            try:
                candidate.unlink()
            except OSError:
                pass
    return removed


def rotate_logs(*, reason: str = "startup") -> dict[str, int]:
    """Prune aged JSONL audit/error logs; rotate/size-cap .local-run stdout captures."""
    days = _retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stats: dict[str, int] = {
        "retention_days": days,
        "audit_pruned": 0,
        "error_pruned": 0,
        "local_run_removed": 0,
        "local_run_rotated": 0,
    }
    for path, key in ((audit_log_path(), "audit_pruned"), (error_log_path(), "error_pruned")):
        _rotate_if_oversized(path)
        stats[key] = _prune_log_family(path, cutoff=cutoff)
    local_stats = _prune_local_run_logs(cutoff)
    stats["local_run_removed"] = local_stats["local_run_removed"]
    stats["local_run_rotated"] = local_stats["local_run_rotated"]
    if any(stats[k] for k in ("audit_pruned", "error_pruned", "local_run_removed", "local_run_rotated")):
        _log.info("log rotation (%s): %s", reason, stats)
    return stats


def rotate_logs_on_startup() -> dict[str, int]:
    """Backward-compatible alias used by bridge lifespan."""
    return rotate_logs(reason="startup")


def _rotation_interval_seconds() -> float:
    raw = os.environ.get("OFDD_LOG_ROTATE_INTERVAL_HOURS", "").strip()
    if not raw:
        return _DEFAULT_ROTATE_INTERVAL_HOURS * 3600.0
    try:
        hours = max(0.5, min(float(raw), 168.0))
        return hours * 3600.0
    except ValueError:
        return _DEFAULT_ROTATE_INTERVAL_HOURS * 3600.0


def start_log_rotation_worker() -> None:
    """Background retention pass so long-lived bridge processes do not grow logs unbounded."""
    import threading
    import time

    interval = _rotation_interval_seconds()
    if interval <= 0:
        return

    def _loop() -> None:
        while True:
            time.sleep(interval)
            try:
                rotate_logs(reason="scheduled")
            except Exception as exc:  # noqa: BLE001
                _log.warning("scheduled log rotation failed: %s", exc)

    threading.Thread(target=_loop, name="log-rotation-worker", daemon=True).start()
