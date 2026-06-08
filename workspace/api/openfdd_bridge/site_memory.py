"""Per-building MEMORY.md and SKILLS.md under workspace/memory/sites/."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import workspace_dir

_SAFE_SITE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_MAX_BODY_CHARS = 200_000


def _sites_root() -> Path:
    root = workspace_dir() / "memory" / "sites"
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_site_id(site_id: str) -> str:
    sid = (site_id or "").strip()
    if not sid or not _SAFE_SITE.match(sid):
        raise ValueError(f"invalid site_id: {site_id!r}")
    return sid


def site_memory_path(site_id: str) -> Path:
    sid = validate_site_id(site_id)
    return _sites_root() / f"{sid}.md"


def site_skills_path(site_id: str) -> Path:
    sid = validate_site_id(site_id)
    d = _sites_root() / sid
    d.mkdir(parents=True, exist_ok=True)
    return d / "SKILLS.md"


def _read_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _write_file(path: Path, text: str) -> None:
    if len(text) > _MAX_BODY_CHARS:
        raise ValueError(f"content exceeds {_MAX_BODY_CHARS} characters")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _default_memory(site_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"# Site memory — {site_id}\n\n"
        f"Curated facts for building-agent check-ins. Promote stable decisions here; "
        f"append session detail to daily notes under `memory/`.\n\n"
        f"## Last updated\n\n{now}\n\n"
        "## BACnet / polling\n\n"
        "## FDD rules / tuning\n\n"
        "## Open loops\n\n"
    )


def _default_skills(site_id: str) -> str:
    return (
        f"# Site skills — {site_id}\n\n"
        "Operator-approved playbooks for this building. The building agent reads this "
        "before auto-tuning or escalating.\n\n"
        "## Check-in cadence\n\n"
        "- Early commissioning: every 6h (21600s cron job)\n"
        "- Stable ops target: daily → every other day → weekly\n\n"
        "## Tuning guardrails\n\n"
        "- Do not change rule thresholds when poll keepup_ratio < 0.85\n"
        "- Human in the loop for any write to rule config\n"
        "- Prefer `bounds_low` / `bounds_high` tweaks over disabling rules\n\n"
        "## Escalation\n\n"
        "- Critical poll offline → building alerts + memory note only (no auto-tune)\n"
    )


def get_site_memory(*, site_id: str, kind: str = "memory") -> dict[str, Any]:
    sid = validate_site_id(site_id)
    if kind == "skills":
        path = site_skills_path(sid)
        default = _default_skills(sid)
    else:
        path = site_memory_path(sid)
        default = _default_memory(sid)
    exists = path.is_file()
    text = _read_file(path) if exists else default
    return {
        "ok": True,
        "site_id": sid,
        "kind": kind,
        "path": str(path),
        "exists": exists,
        "bytes": len(text.encode("utf-8")),
        "content": text,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        if exists
        else None,
    }


def put_site_memory(
    *,
    site_id: str,
    content: str,
    kind: str = "memory",
    mode: str = "replace",
) -> dict[str, Any]:
    sid = validate_site_id(site_id)
    if kind == "skills":
        path = site_skills_path(sid)
    else:
        path = site_memory_path(sid)
    text = str(content or "")
    if mode == "append":
        existing = _read_file(path)
        sep = "\n\n" if existing and not existing.endswith("\n") else "\n"
        text = existing + sep + text
    elif mode != "replace":
        raise ValueError(f"unsupported mode: {mode}")
    _write_file(path, text)
    return {
        "ok": True,
        "site_id": sid,
        "kind": kind,
        "path": str(path),
        "bytes": len(text.encode("utf-8")),
        "mode": mode,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def append_checkin_note(*, site_id: str, summary: str, detail: str = "") -> dict[str, Any]:
    """Append a dated block to site MEMORY.md (building agent check-ins)."""
    sid = validate_site_id(site_id)
    path = site_memory_path(sid)
    if not path.is_file():
        _write_file(path, _default_memory(sid))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    block = f"## Check-in {stamp}\n\n{summary.strip()}\n"
    if detail.strip():
        block += f"\n{detail.strip()}\n"
    return put_site_memory(site_id=sid, content=block, kind="memory", mode="append")
