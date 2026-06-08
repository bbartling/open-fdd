from __future__ import annotations

import csv
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from bacnet_toolshed.models import (
    DeviceInstanceRequest,
    DiscoverRequest,
    ReadMultiplePropertiesRequest,
    WritePropertyRequest,
    parse_object_identifier_parts,
)
from bacpypes3.primitivedata import PropertyIdentifier

from ..bacnet_driver_store import (
    clear_registry,
    delete_device,
    delete_point,
    driver_tree,
    merge_commission_rows,
    remap_device,
    set_device_poll,
    set_point_poll,
    sync_discovery,
)
from ..bacnet_model_sync import merge_device_into_model
from ..commission_client import (
    bacnet_priority_array as commission_priority_array,
    bacnet_read as commission_read,
    bacnet_read_multiple as commission_read_multiple,
    bacnet_write as commission_write,
    commission_health,
    commission_override_scan_once,
    commission_override_status,
    commission_poll_once,
    commission_poll_status,
    commission_status,
    get_job,
    server_points as commission_server_points,
    start_discover,
    start_point_discovery,
    start_supervisory_check,
    whois as commission_whois,
)
from ..bacnet_write_guard import (
    ensure_writes_enabled,
    reject_if_dry_run,
    validate_priority,
    validate_write_target,
)
from ..bacnet_access import require_bacnet_discovery, require_bacnet_mutation, require_bacnet_poll_config
from ..security import bacnet_discovery_mutations_enabled
from ..deps import require_roles
from ..bacnet_poll_ingest import ingest_poll_samples_to_feather

_log = logging.getLogger(__name__)
_ingest_lock = threading.Lock()
from ..paths import bacnet_poll_csv, data_dir, workspace_dir

router = APIRouter(tags=["bacnet"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_DISCOVERY = Depends(require_bacnet_discovery)
_MUTATION = Depends(require_bacnet_mutation)
_POLL = Depends(require_bacnet_poll_config)
_WRITE = Depends(require_roles("integrator"))
_INTEGRATOR = Depends(require_roles("integrator"))


class BridgeSingleReadRequest(BaseModel):
    """Bridge API body — includes device_address even when image bacnet_toolshed lags."""

    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    object_identifier: str
    property_identifier: str = "present-value"

    @field_validator("object_identifier")
    @classmethod
    def validate_object_identifier(cls, value: str) -> str:
        parse_object_identifier_parts(value)
        return value

    @field_validator("property_identifier")
    @classmethod
    def validate_property_identifier(cls, value: str) -> str:
        try:
            PropertyIdentifier(value)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid property identifier: {value}") from None
        return value


class BridgeReadPriorityArrayRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    object_identifier: str

    @field_validator("object_identifier")
    @classmethod
    def validate_object_identifier(cls, value: str) -> str:
        parse_object_identifier_parts(value)
        return value


class BridgeReadMultipleRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    requests: list[ReadMultiplePropertiesRequest]


class ImportToModelBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    site_id: str | None = None
    equipment_name: str | None = None
    objects: list[dict[str, Any]] | None = None


class SyncDiscoveryBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""
    objects: list[dict[str, Any]] = Field(default_factory=list)
    replace: bool = False
    merge_existing: bool = False


class MergeCommissionRowsBody(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    enable_poll: bool = True


class PointPollBody(BaseModel):
    point_id: str
    enabled: bool = True
    poll_interval_s: Literal[60, 300, 900, 1800, 3600] = 60


class DevicePollBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    enabled: bool = True
    poll_interval_s: Literal[60, 300, 900, 1800, 3600] = 60


class RemapDeviceBody(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    new_device_instance: int | None = Field(default=None, ge=0, le=4194303)
    new_device_address: str | None = None

_SAFE_SITE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_site_id(site_id: str) -> str:
    sid = site_id.strip()
    if not _SAFE_SITE_ID.match(sid):
        raise HTTPException(status_code=400, detail="invalid site_id")
    return sid


def _proxy_error(status: int, payload: object) -> HTTPException:
    detail = payload if isinstance(payload, dict) else {"error": str(payload)}
    return HTTPException(status_code=status, detail=detail)


@router.get("/config/bacnet", dependencies=[_READ])
def bacnet_config() -> dict:
    points = workspace_dir() / "bacnet" / "commissioning" / "points.csv"
    discovered = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    commission_ok = False
    commission_detail: dict | None = None
    status_code, payload = commission_health()
    if status_code == 200 and isinstance(payload, dict):
        commission_ok = bool(payload.get("ok"))
        commission_detail = payload
    server_pts: list[dict] = []
    sp_status, sp_payload = commission_server_points()
    if sp_status == 200 and isinstance(sp_payload, dict):
        server_pts = sp_payload.get("points") or []
    return {
        "points_csv": str(points),
        "points_exists": points.is_file(),
        "discovered_csv": str(discovered),
        "discovered_exists": discovered.is_file(),
        "poll_csv": str(bacnet_poll_csv()),
        "poll_exists": bacnet_poll_csv().is_file(),
        "toolshed_readme": "bacnet_toolshed/README.md",
        "commission_agent_ok": commission_ok,
        "commission_agent": commission_detail,
        "openfdd_server_points": server_pts,
        "discovery_mutations_enabled": bacnet_discovery_mutations_enabled(),
    }


@router.get("/api/bacnet/commission/status", dependencies=[_READ])
def bacnet_commission_status() -> dict:
    status_code, payload = commission_status()
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/server/points", dependencies=[_READ])
def bacnet_server_points() -> dict:
    status_code, payload = commission_server_points()
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/inventory", dependencies=[_READ])
def bacnet_inventory() -> dict:
    """Grouped device → points from points_discovered.csv (after CSV discover job)."""
    discovered = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    if not discovered.is_file():
        return {"ok": True, "devices": [], "point_count": 0, "path": str(discovered)}
    devices: dict[str, dict] = {}
    point_count = 0
    with discovered.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            inst = str(row.get("device_instance") or "").strip()
            if not inst:
                continue
            dev = devices.setdefault(
                inst,
                {
                    "device_instance": inst,
                    "device_address": str(row.get("device_address") or ""),
                    "points": [],
                },
            )
            if not dev["device_address"] and row.get("device_address"):
                dev["device_address"] = str(row["device_address"])
            obj_type = str(row.get("object_type") or "")
            obj_inst = str(row.get("object_instance") or "")
            point = {
                "object_identifier": f"{obj_type},{obj_inst}" if obj_type else "",
                "object_name": str(row.get("object_name") or ""),
                "description": str(row.get("description") or ""),
                "present_value": str(row.get("present_value") or ""),
                "units": str(row.get("units") or ""),
                "point_id": str(row.get("point_id") or ""),
            }
            dev["points"].append(point)
            point_count += 1
    device_list = sorted(devices.values(), key=lambda d: int(d["device_instance"]))
    for dev in device_list:
        dev["point_count"] = len(dev["points"])
    return {
        "ok": True,
        "devices": device_list,
        "point_count": point_count,
        "path": str(discovered),
    }


@router.post("/api/bacnet/import-to-model", dependencies=[_INTEGRATOR])
def bacnet_import_to_model(body: ImportToModelBody) -> dict:
    """Merge BACnet discovery into model.json (integrator role)."""
    try:
        return merge_device_into_model(
            device_instance=body.device_instance,
            device_address=body.device_address,
            objects=body.objects,
            site_id=body.site_id,
            equipment_name=body.equipment_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/bacnet/driver/tree", dependencies=[_READ])
def bacnet_driver_tree() -> dict:
    return driver_tree()


@router.post("/api/bacnet/driver/sync-discovery", dependencies=[_MUTATION])
def bacnet_sync_discovery(body: SyncDiscoveryBody) -> dict:
    try:
        return sync_discovery(
            device_instance=body.device_instance,
            device_address=body.device_address,
            objects=body.objects,
            replace=body.replace,
            merge_existing=body.merge_existing,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/bacnet/driver/merge-rows", dependencies=[_INTEGRATOR])
def bacnet_merge_commission_rows(body: MergeCommissionRowsBody) -> dict:
    """Upsert commission CSV rows into discovered + poll lists (integrator)."""
    try:
        return merge_commission_rows(body.rows, enable_poll=body.enable_poll)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/bacnet/driver/point", dependencies=[_POLL])
def bacnet_set_point_poll(body: PointPollBody) -> dict:
    try:
        return set_point_poll(
            point_id=body.point_id,
            enabled=body.enabled,
            poll_interval_s=body.poll_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/bacnet/driver/device", dependencies=[_POLL])
def bacnet_set_device_poll(body: DevicePollBody) -> dict:
    try:
        return set_device_poll(
            device_instance=body.device_instance,
            enabled=body.enabled,
            poll_interval_s=body.poll_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/bacnet/driver/point/{point_id}", dependencies=[_MUTATION])
def bacnet_delete_point(point_id: str) -> dict:
    return delete_point(point_id=point_id)


@router.delete("/api/bacnet/driver/device/{device_instance}", dependencies=[_MUTATION])
def bacnet_delete_device(device_instance: int) -> dict:
    return delete_device(device_instance=device_instance)


@router.delete("/api/bacnet/driver/registry", dependencies=[_MUTATION])
def bacnet_clear_registry() -> dict:
    """Clear all BACnet devices from driver CSVs, poll samples, and data model."""
    return clear_registry(sync_model=True, sync_ttl=True)


@router.patch("/api/bacnet/driver/device/remap", dependencies=[_MUTATION])
def bacnet_remap_device(body: RemapDeviceBody) -> dict:
    if body.new_device_instance is None and not (body.new_device_address or "").strip():
        raise HTTPException(status_code=400, detail="provide new_device_instance and/or new_device_address")
    try:
        return remap_device(
            device_instance=body.device_instance,
            new_device_instance=body.new_device_instance,
            new_device_address=(body.new_device_address or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/bacnet/discover", dependencies=[_DISCOVERY])
def bacnet_discover_devices(body: DiscoverRequest) -> dict:
    if body.range_low > body.range_high:
        raise HTTPException(status_code=400, detail="range_low must be <= range_high")
    status_code, payload = start_discover(body.range_low, body.range_high)
    if status_code not in (200, 202):
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/whois", dependencies=[_DISCOVERY])
def bacnet_whois(body: DiscoverRequest) -> dict:
    status_code, payload = commission_whois(body.range_low, body.range_high)
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/read", dependencies=[_READ])
def bacnet_read_property(body: BridgeSingleReadRequest) -> dict:
    status_code, payload = commission_read(
        body.device_instance,
        body.object_identifier,
        body.property_identifier,
        device_address=body.device_address,
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    if body.property_identifier == "present-value" and isinstance(payload, dict):
        from ..bacnet_driver_store import record_ondemand_present_value

        val = payload.get("value")
        formatted = "—" if val is None else (str(val) if not isinstance(val, (dict, list)) else str(val))
        record_ondemand_present_value(
            device_instance=body.device_instance,
            object_identifier=body.object_identifier,
            present_value=formatted,
        )
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/read-multiple", dependencies=[_READ])
def bacnet_read_multiple_properties(body: BridgeReadMultipleRequest) -> dict:
    requests = [
        {"object_identifier": r.object_identifier, "property_identifier": r.property_identifier}
        for r in body.requests
    ]
    status_code, payload = commission_read_multiple(
        body.device_instance, requests, device_address=body.device_address
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/priority-array", dependencies=[_READ])
def bacnet_read_priority_array(body: BridgeReadPriorityArrayRequest) -> dict:
    status_code, payload = commission_priority_array(
        body.device_instance,
        body.object_identifier,
        device_address=body.device_address,
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/point-discovery", dependencies=[_DISCOVERY])
def bacnet_point_discovery(body: DeviceInstanceRequest) -> dict:
    status_code, payload = start_point_discovery(body.device_instance, body.device_address)
    if status_code not in (200, 202):
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/supervisory-check", dependencies=[_DISCOVERY])
def bacnet_supervisory_check(body: DeviceInstanceRequest) -> dict:
    status_code, payload = start_supervisory_check(body.device_instance, body.device_address)
    if status_code not in (200, 202):
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/write", dependencies=[_WRITE])
def bacnet_write_property(body: WritePropertyRequest, request: Request) -> dict:
    user = getattr(request.state, "user", None)
    body_dump = body.model_dump()
    ensure_writes_enabled(request=request, user=user, body=body_dump)
    priority = validate_priority(body.priority)
    validate_write_target(
        device_instance=body.device_instance,
        object_identifier=body.object_identifier,
        property_identifier=body.property_identifier,
        priority=priority,
        value=body.value,
        request=request,
        user=user,
    )
    reject_if_dry_run(request=request, user=user, body=body_dump)
    status_code, payload = commission_write(
        body.device_instance,
        body.object_identifier,
        body.property_identifier,
        body.value,
        priority,
    )
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/jobs/{job_id}", dependencies=[_READ])
def bacnet_job_status(job_id: str) -> dict:
    if not re.match(r"^[a-f0-9]{8,32}$", job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    status_code, payload = get_job(job_id)
    if status_code != 200:
        raise _proxy_error(status_code, payload)
    return payload  # type: ignore[return-value]


def _enrich_poll_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Add browser-friendly local time alongside UTC poll timestamp."""
    out = dict(payload)
    at_raw = str(payload.get("at") or "").strip()
    tz_name = os.environ.get("OFDD_SITE_TIMEZONE", "America/Chicago").strip() or "America/Chicago"
    out["site_timezone"] = tz_name
    if not at_raw:
        return out
    try:
        ts = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        local = ts.astimezone(ZoneInfo(tz_name))
        out["at_utc"] = at_raw
        out["at_local"] = local.isoformat()
        out["at_local_display"] = local.strftime("%Y-%m-%d %H:%M:%S %Z")
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        out["at_utc"] = at_raw
    return out


@router.get("/api/bacnet/overrides/status", dependencies=[_READ])
def bacnet_override_status() -> dict:
    code, payload = commission_override_status()
    if code != 200:
        raise _proxy_error(code, payload)
    try:
        from bacnet_toolshed.override_registry import export_csv_text, scan_status

        if isinstance(payload, dict):
            payload = {**scan_status(), **payload}
        payload["export_row_count"] = max(0, export_csv_text().count("\n") - 1)
    except Exception:
        pass
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/overrides/export", dependencies=[_READ])
def bacnet_override_export() -> Response:
    try:
        from bacnet_toolshed.override_registry import export_csv_text

        body = export_csv_text()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="bacnet_overrides_export.csv"'},
    )


@router.post("/api/bacnet/overrides/scan-once", dependencies=[_READ])
def bacnet_override_scan_once() -> dict:
    code, payload = commission_override_scan_once()
    if code != 200:
        raise _proxy_error(code, payload)
    return payload  # type: ignore[return-value]


@router.get("/api/bacnet/poll/status", dependencies=[_READ])
def bacnet_poll_status() -> dict:
    code, payload = commission_poll_status()
    if code != 200:
        raise _proxy_error(code, payload)
    if isinstance(payload, dict):
        return _enrich_poll_status(payload)
    return payload  # type: ignore[return-value]


@router.post("/api/bacnet/poll/once", dependencies=[_DISCOVERY])
def bacnet_trigger_poll() -> dict:
    code, payload = commission_poll_once()
    if code != 200:
        raise _proxy_error(code, payload)
    ingest = ingest_poll_samples_to_feather()
    return {"poll": payload, "ingest": ingest}


def _lan_internal_ingest_allowed() -> bool:
    raw = os.environ.get("OFDD_ALLOW_LAN_INTERNAL_INGEST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _internal_ingest_client_allowed(request: Request) -> bool:
    """Loopback always allowed; RFC1918 only when OFDD_ALLOW_LAN_INTERNAL_INGEST is set."""
    host = (request.client.host if request.client else "").strip()
    if host in {"127.0.0.1", "::1"}:
        return True
    if not _lan_internal_ingest_allowed():
        return False
    if host.startswith(("10.", "192.168.")):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                return 16 <= second <= 31
            except ValueError:
                return False
    return False


def _run_ingest_background() -> None:
    if not _ingest_lock.acquire(blocking=False):
        return
    try:
        result = ingest_poll_samples_to_feather()
        if not result.get("ok"):
            _log.warning("bacnet poll ingest: %s", result.get("reason") or result)
    except Exception:
        _log.exception("bacnet poll ingest failed")
    finally:
        _ingest_lock.release()


@router.post("/internal/bacnet/ingest-samples")
def internal_ingest_poll_samples(request: Request) -> dict:
    if not _internal_ingest_client_allowed(request):
        raise HTTPException(status_code=403, detail="localhost only")
    if _ingest_lock.locked():
        return {"ok": True, "queued": False, "reason": "ingest already running"}
    threading.Thread(target=_run_ingest_background, name="bacnet-ingest", daemon=True).start()
    return {"ok": True, "queued": True}


@router.post("/ingest/bacnet", dependencies=[_READ])
def ingest_bacnet(site_id: str | None = None) -> dict:
    if site_id:
        _validate_site_id(site_id)
    result = ingest_poll_samples_to_feather()
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "ingest failed"))
    return result
