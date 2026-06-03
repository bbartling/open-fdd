"""BACnet write_property gates for OT edge deployments."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from .audit import write_audit
from .paths import workspace_dir
from .security import bacnet_writes_enabled

_log = logging.getLogger(__name__)

_OBJECT_ID_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9-]*),(\d+)$")


def _allowlist_path() -> Path:
    return workspace_dir() / "bacnet" / "write_allowlist.json"


def load_write_allowlist() -> dict[str, Any] | None:
    path = _allowlist_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"invalid write allowlist: {exc}") from exc
    return raw if isinstance(raw, dict) else None


def _device_allowlist(devices: list[Any]) -> set[int]:
    allowed: set[int] = set()
    skipped: list[str] = []
    for entry in devices:
        try:
            allowed.add(int(entry))
        except (TypeError, ValueError):
            skipped.append(str(entry))
    if skipped:
        _log.warning("write allowlist: skipped non-numeric device_instances: %s", skipped)
    if not allowed:
        raise HTTPException(
            status_code=500,
            detail="write allowlist device_instances has no valid numeric entries",
        )
    return allowed


def validate_priority(priority: int | None) -> int:
    if priority is None:
        raise HTTPException(
            status_code=400,
            detail="priority is required for BACnet writes (1=manual override … 16=default)",
        )
    if priority < 1 or priority > 16:
        raise HTTPException(status_code=400, detail="priority must be between 1 and 16")
    return priority


def validate_write_target(*, device_instance: int, object_identifier: str) -> None:
    oid = object_identifier.strip()
    if not _OBJECT_ID_RE.match(oid):
        raise HTTPException(status_code=400, detail="invalid object_identifier (e.g. analog-value,1)")
    allowlist = load_write_allowlist()
    if allowlist is None:
        return
    devices = allowlist.get("device_instances")
    if isinstance(devices, list) and devices:
        allowed = _device_allowlist(devices)
        if device_instance not in allowed:
            raise HTTPException(status_code=403, detail=f"device {device_instance} not in write allowlist")
    objects = allowlist.get("object_identifiers")
    if isinstance(objects, list) and objects:
        allowed_objs = {str(x).strip().lower() for x in objects}
        if oid.lower() not in allowed_objs:
            raise HTTPException(status_code=403, detail=f"object {oid} not in write allowlist")


def ensure_writes_enabled(*, request: Request, user: dict | None, body: dict[str, Any]) -> None:
    if bacnet_writes_enabled():
        return
    write_audit(
        event_type="bacnet.command",
        action="write denied (disabled)",
        outcome="failure",
        severity="warning",
        request=request,
        user=user,
        resource_type="bacnet",
        resource_id=str(body.get("object_identifier") or ""),
        detail={"device_instance": body.get("device_instance"), "reason": "OFDD_ENABLE_BACNET_WRITE not set"},
    )
    raise HTTPException(
        status_code=403,
        detail="BACnet writes are disabled — set OFDD_ENABLE_BACNET_WRITE=1 to enable",
    )
