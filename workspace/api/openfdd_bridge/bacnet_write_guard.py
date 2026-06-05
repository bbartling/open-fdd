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
from .security import bacnet_write_allow_any, bacnet_writes_enabled

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
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=500,
            detail=f"write allowlist must be a JSON object, got {type(raw).__name__} ({path.name})",
        )
    return raw


def _device_allowlist(devices: list[Any]) -> set[int]:
    allowed: set[int] = set()
    skipped: list[str] = []
    for entry in devices:
        if isinstance(entry, bool):
            skipped.append(str(entry))
            continue
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


def _normalize_entries(allowlist: dict[str, Any]) -> list[dict[str, Any]]:
    writes = allowlist.get("writes")
    if isinstance(writes, list) and writes:
        out: list[dict[str, Any]] = []
        for entry in writes:
            if isinstance(entry, dict):
                out.append(entry)
        if out:
            return out
    devices = allowlist.get("device_instances")
    objects = allowlist.get("object_identifiers")
    dev_list = devices if isinstance(devices, list) else []
    obj_list = objects if isinstance(objects, list) else []
    if not dev_list and not obj_list:
        return []
    legacy: list[dict[str, Any]] = []
    for dev in dev_list:
        try:
            di = int(dev)
        except (TypeError, ValueError):
            continue
        for obj in obj_list or [None]:
            row: dict[str, Any] = {"device_instance": di}
            if obj is not None:
                row["object_identifier"] = str(obj).strip()
            legacy.append(row)
    if not legacy and dev_list:
        for dev in dev_list:
            try:
                legacy.append({"device_instance": int(dev)})
            except (TypeError, ValueError):
                continue
    return legacy


def _value_in_allowed(value: Any, allowed_values: list[Any]) -> bool:
    if value in allowed_values:
        return True
    sval = str(value).strip().lower()
    return any(str(v).strip().lower() == sval for v in allowed_values)


def _match_write_entry(
    entry: dict[str, Any],
    *,
    device_instance: int,
    object_identifier: str,
    property_identifier: str,
    priority: int | None,
    value: Any,
) -> bool:
    try:
        if int(entry.get("device_instance")) != device_instance:
            return False
    except (TypeError, ValueError):
        return False
    obj = str(entry.get("object_identifier") or "").strip().lower()
    if obj and obj != object_identifier.strip().lower():
        return False
    prop = str(entry.get("property_identifier") or "").strip().lower()
    if prop and prop != property_identifier.strip().lower():
        return False
    pmin = entry.get("priority_min")
    pmax = entry.get("priority_max")
    if priority is not None:
        try:
            if pmin is not None and priority < int(pmin):
                return False
            if pmax is not None and priority > int(pmax):
                return False
        except (TypeError, ValueError):
            return False
    vmin = entry.get("value_min")
    vmax = entry.get("value_max")
    if vmin is not None or vmax is not None:
        try:
            fval = float(value)
            if vmin is not None and fval < float(vmin):
                return False
            if vmax is not None and fval > float(vmax):
                return False
        except (TypeError, ValueError):
            return False
    allowed_values = entry.get("allowed_values")
    if isinstance(allowed_values, list) and allowed_values:
        if not _value_in_allowed(value, allowed_values):
            return False
    return True


def validate_priority(priority: int | None) -> int:
    if priority is None:
        raise HTTPException(
            status_code=400,
            detail="priority is required for BACnet writes (1=manual override … 16=default)",
        )
    if priority < 1 or priority > 16:
        raise HTTPException(status_code=400, detail="priority must be between 1 and 16")
    return priority


def validate_write_target(
    *,
    device_instance: int,
    object_identifier: str,
    property_identifier: str = "present-value",
    priority: int | None = None,
    value: Any = None,
    request: Request | None = None,
    user: dict | None = None,
) -> None:
    oid = object_identifier.strip()
    if not _OBJECT_ID_RE.match(oid):
        raise HTTPException(status_code=400, detail="invalid object_identifier (e.g. analog-value,1)")
    allowlist = load_write_allowlist()
    if allowlist is None:
        if bacnet_write_allow_any():
            write_audit(
                event_type="bacnet.command",
                action="write allow-any",
                outcome="success",
                severity="warning",
                request=request,
                user=user,
                resource_type="bacnet",
                resource_id=oid,
                detail={
                    "device_instance": device_instance,
                    "property_identifier": property_identifier,
                    "reason": "OFDD_BACNET_WRITE_ALLOW_ANY",
                },
            )
            return
        write_audit(
            event_type="bacnet.command",
            action="write denied (no allowlist)",
            outcome="failure",
            severity="warning",
            request=request,
            user=user,
            resource_type="bacnet",
            resource_id=oid,
            detail={"device_instance": device_instance, "reason": "missing write_allowlist.json"},
        )
        raise HTTPException(
            status_code=403,
            detail="BACnet writes require workspace/bacnet/write_allowlist.json when OFDD_ENABLE_BACNET_WRITE=1",
        )
    entries = _normalize_entries(allowlist)
    if not entries:
        write_audit(
            event_type="bacnet.command",
            action="write denied (empty allowlist)",
            outcome="failure",
            severity="warning",
            request=request,
            user=user,
            resource_type="bacnet",
            resource_id=oid,
            detail={"device_instance": device_instance},
        )
        raise HTTPException(status_code=403, detail="write allowlist has no valid entries")
    if any(_match_write_entry(
        entry,
        device_instance=device_instance,
        object_identifier=oid,
        property_identifier=property_identifier,
        priority=priority,
        value=value,
    ) for entry in entries):
        return
    write_audit(
        event_type="bacnet.command",
        action="write denied (not in allowlist)",
        outcome="failure",
        severity="warning",
        request=request,
        user=user,
        resource_type="bacnet",
        resource_id=oid,
        detail={
            "device_instance": device_instance,
            "property_identifier": property_identifier,
            "priority": priority,
        },
    )
    raise HTTPException(status_code=403, detail="write target not in allowlist")


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
