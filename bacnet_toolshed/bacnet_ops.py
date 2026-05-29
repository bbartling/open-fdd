"""BACnet read/write/discover/supervisory ops (ported from diy-bacnet-server client_utils)."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple, Union

from bacpypes3.apdu import AbortPDU, AbortReason, ErrorRejectAbortNack, ErrorType
from bacpypes3.app import Application
from bacpypes3.constructeddata import AnyAtomic, Array, List as BacList, Sequence
from bacpypes3.json.util import atomic_encode, extendedlist_to_json_list, sequence_to_json
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Atomic, Null, ObjectIdentifier, ObjectType
from bacpypes3.vendor import get_vendor_info

from bacnet_toolshed.discover_lib import object_identifiers
from bacnet_toolshed.rpm import read_multiple_chunked, unwrap_value

logger = logging.getLogger(__name__)

RPM_CHUNK_SIZE = 25

COMMANDABLE_TYPES = {
    "analog-output",
    "analog-value",
    "binary-output",
    "binary-value",
    "multi-state-output",
    "multi-state-value",
    "integer-value",
    "large-analog-value",
    "positive-integer-value",
}


class BacnetOpsError(Exception):
    def __init__(self, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.data = data or {}


def normalize_oid(oid: Any) -> str:
    if oid is None:
        return ""
    s = str(oid).strip()
    if s.startswith("(") and ")" in s:
        return s[1 : s.index(")")].replace(" ", "")
    parts = s.split(",", 1)
    return ",".join(p.strip() for p in parts) if len(parts) == 2 else s


def encode_rpm_value(property_value: Any) -> Any:
    if isinstance(property_value, ErrorType):
        return f"Error: {property_value.errorClass}, {property_value.errorCode}"
    if isinstance(property_value, AnyAtomic):
        property_value = property_value.get_value()
    if isinstance(property_value, Atomic):
        return atomic_encode(property_value)
    if isinstance(property_value, Sequence):
        return sequence_to_json(property_value)
    if isinstance(property_value, (Array, BacList)):
        return extendedlist_to_json_list(property_value)
    if isinstance(property_value, (list, tuple)) and property_value:
        first = property_value[0]
        if hasattr(first, "_choice"):
            out = []
            for pv in property_value:
                choice = pv._choice
                val = getattr(pv, choice, None)
                out.append(
                    {
                        choice: []
                        if val is None and choice == "null"
                        else (val if val is not None else [])
                    }
                )
            return out
        try:
            return extendedlist_to_json_list(property_value)
        except Exception:
            pass
    if isinstance(property_value, (int, float, str, bool, type(None))):
        return property_value
    return str(property_value)


async def get_device_address(app: Application, device_instance: int) -> Address:
    device_info = app.device_info_cache.instance_cache.get(device_instance)
    if device_info:
        return device_info.device_address
    i_ams = await app.who_is(device_instance, device_instance)
    if not i_ams:
        raise BacnetOpsError(f"Device {device_instance} not found")
    if len(i_ams) > 1:
        raise BacnetOpsError(f"Multiple devices found for instance {device_instance}")
    return i_ams[0].pduSource


async def perform_who_is(
    app: Application, start_instance: int, end_instance: int
) -> list[dict[str, Any]]:
    i_ams = await app.who_is(start_instance, end_instance)
    if not i_ams:
        return []
    result: list[dict[str, Any]] = []
    for i_am in i_ams:
        device_address = i_am.pduSource
        device_identifier = i_am.iAmDeviceIdentifier
        try:
            device_description = await app.read_property(
                device_address, device_identifier, "description"
            )
        except ErrorRejectAbortNack as err:
            device_description = f"Error: {err}"
        result.append(
            {
                "i-am-device-identifier": str(device_identifier),
                "device-address": str(device_address),
                "device-description": str(device_description),
                "max-apdu-length-accepted": i_am.maxAPDULengthAccepted,
                "segmentation-supported": str(i_am.segmentationSupported),
                "vendor-id": i_am.vendorID,
            }
        )
    return result


async def rpm_chunked(
    app: Application,
    address: Union[str, Address],
    requests: List[Tuple[str, str]],
    chunk_size: int = RPM_CHUNK_SIZE,
) -> List[dict[str, Any]]:
    if not requests:
        return []
    addr = str(address)
    combined: List[dict[str, Any]] = []
    for i in range(0, len(requests), chunk_size):
        chunk = requests[i : i + chunk_size]
        objects: dict[str, list[str]] = {}
        for obj_id, prop_id in chunk:
            objects.setdefault(obj_id, []).append(prop_id)
        try:
            raw = await read_multiple_chunked(app, addr, objects, chunk_size=len(chunk))
            for obj_id, prop_id in chunk:
                key1 = f"{obj_id}:{prop_id}"
                key2 = f"{obj_id}:present-value"
                if key1 in raw:
                    val = raw[key1]
                elif key2 in raw:
                    val = raw[key2]
                else:
                    val = None
                combined.append(
                    {
                        "object_identifier": obj_id,
                        "property_identifier": prop_id,
                        "property_array_index": None,
                        "value": val,
                    }
                )
        except Exception as exc:
            for obj_id, prop_id in chunk:
                combined.append(
                    {
                        "object_identifier": obj_id,
                        "property_identifier": prop_id,
                        "error": str(exc),
                    }
                )
    return combined


async def point_discovery(app: Application, instance_id: int) -> dict[str, Any]:
    i_ams = await app.who_is(instance_id, instance_id)
    if not i_ams:
        raise BacnetOpsError(
            f"No response from device {instance_id} to Who-Is",
            {"instance": instance_id},
        )

    i_am = i_ams[0]
    device_address = i_am.pduSource
    device_identifier = i_am.iAmDeviceIdentifier
    vendor_info = get_vendor_info(i_am.vendorID)

    try:
        object_list = await object_identifiers(app, device_address, device_identifier)
    except AbortPDU as err:
        if err.apduAbortRejectReason != AbortReason.segmentationNotSupported:
            logger.error("Abort reading object-list: %s", err)
        return {
            "device_address": str(device_address),
            "device_instance": instance_id,
            "objects": [],
        }

    rpm_requests_names = []
    for obj_id in object_list:
        if vendor_info.get_object_class(obj_id[0]):
            rpm_requests_names.append((f"{obj_id[0]},{obj_id[1]}", "object-name"))
    name_results = await rpm_chunked(app, device_address, rpm_requests_names, chunk_size=15)
    name_map = {
        normalize_oid(r.get("object_identifier")): r.get("value")
        for r in name_results
        if "error" not in r
    }

    rpm_requests_pa = []
    for obj_id in object_list:
        if str(obj_id[0]).lower() in COMMANDABLE_TYPES:
            rpm_requests_pa.append((f"{obj_id[0]},{obj_id[1]}", "priority-array"))
    pa_results = await rpm_chunked(app, device_address, rpm_requests_pa, chunk_size=15)
    commandable_oids = {
        normalize_oid(r.get("object_identifier"))
        for r in pa_results
        if "error" not in r and r.get("value") is not None
    }

    names_list = [str(name_map.get(normalize_oid(obj_id), "ERROR - Missing Data")) for obj_id in object_list]
    return {
        "device_address": str(device_address),
        "device_instance": instance_id,
        "objects": [
            {
                "object_identifier": normalize_oid(oid),
                "name": name,
                "commandable": normalize_oid(oid) in commandable_oids,
            }
            for oid, name in zip(object_list, names_list)
        ],
    }


def _flatten_priority_slot(value: Any) -> tuple[str | None, Any] | None:
    if isinstance(value, dict):
        if "null" in value:
            return None
        keys = [k for k in value if k != "null"]
        if not keys:
            return None
        type_name = keys[0]
        return type_name, value[type_name]
    if value is None or (isinstance(value, str) and (value == "null" or value.startswith("Error:"))):
        return None
    type_name = "real" if isinstance(value, (int, float)) else type(value).__name__
    return type_name, value


async def supervisory_logic_check(app: Application, instance_id: int) -> dict[str, Any]:
    result = await point_discovery(app, instance_id)
    device_address = result["device_address"]
    objects = result["objects"]
    if not device_address or not objects:
        return {
            "device_id": instance_id,
            "address": device_address,
            "points": [],
            "points_with_overrides": [],
            "summary": {
                "total_points": 0,
                "with_priority_array": 0,
                "without_priority_array": 0,
                "points_with_override_count": 0,
            },
        }

    points: list[dict[str, Any]] = []
    points_with_overrides_detail: dict[str, list[dict[str, Any]]] = {}
    name_by_oid = {obj["object_identifier"]: obj["name"] for obj in objects}
    total_points = len(objects)
    points_with_priority_array = 0
    points_without_priority_array = 0

    commandable_list = [
        (obj["object_identifier"], obj["name"])
        for obj in objects
        if obj.get("commandable", False)
    ]
    by_oid: dict[str, list[tuple[int | None, Any]]] = {}
    if commandable_list:
        rpm_requests = [(oid, "priority-array") for oid, _ in commandable_list]
        rpm_results = await rpm_chunked(app, device_address, rpm_requests)
        for r in rpm_results:
            if "error" in r:
                continue
            oid = normalize_oid(r.get("object_identifier", ""))
            idx = r.get("property_array_index")
            val = r.get("value")
            if idx is None and isinstance(val, list):
                for i, slot in enumerate(val):
                    by_oid.setdefault(oid, []).append((i, slot))
            else:
                by_oid.setdefault(oid, []).append((idx if idx is not None else 0, val))

    for obj in objects:
        if not obj.get("commandable", False):
            points_without_priority_array += 1
            continue
        priority_slots = by_oid.get(obj["object_identifier"], [])
        if not priority_slots:
            points_without_priority_array += 1
            continue
        points_with_priority_array += 1
        for idx, value in priority_slots:
            flat = _flatten_priority_slot(value)
            if not flat:
                continue
            type_name, raw_val = flat
            priority_level = (idx if idx is not None else 0) + 1
            slot_info = {
                "priority_level": priority_level,
                "type": type_name,
                "value": raw_val,
            }
            points.append(
                {
                    "priority_level": priority_level,
                    "object_identifier": obj["object_identifier"],
                    "object_name": obj["name"],
                    "type": type_name,
                    "value": raw_val,
                }
            )
            points_with_overrides_detail.setdefault(obj["object_identifier"], []).append(slot_info)

    points_with_overrides = []
    for oid, slots in points_with_overrides_detail.items():
        priority_levels = [s["priority_level"] for s in slots]
        points_with_overrides.append(
            {
                "object_identifier": oid,
                "object_name": name_by_oid.get(oid, ""),
                "override_priority_levels": priority_levels,
                "has_multiple_overrides": len(priority_levels) > 1,
                "overrides": slots,
            }
        )

    return {
        "device_id": instance_id,
        "address": device_address,
        "points": points,
        "points_with_overrides": points_with_overrides,
        "summary": {
            "total_points": total_points,
            "with_priority_array": points_with_priority_array,
            "without_priority_array": points_without_priority_array,
            "points_with_override_count": len(points_with_overrides),
        },
    }


def parse_property_identifier(property_identifier: str) -> tuple[str, int | None]:
    if "," in property_identifier:
        prop_id, prop_index = property_identifier.split(",", 1)
        return prop_id.strip(), int(prop_index.strip())
    return property_identifier.strip(), None


async def bacnet_read(
    app: Application,
    device_instance: int,
    object_identifier: str,
    property_identifier: str,
) -> dict[str, Any]:
    address = await get_device_address(app, device_instance)
    obj_id = ObjectIdentifier(object_identifier)
    value = await app.read_property(address, obj_id, property_identifier)
    if isinstance(value, AnyAtomic):
        value = value.get_value()
    if isinstance(value, Atomic):
        encoded = atomic_encode(value)
    elif isinstance(value, Sequence):
        encoded = sequence_to_json(value)
    elif isinstance(value, (Array, BacList)):
        encoded = extendedlist_to_json_list(value)
    else:
        encoded = encode_rpm_value(value)
    return {property_identifier: encoded}


async def bacnet_write(
    app: Application,
    device_instance: int,
    object_identifier: str,
    property_identifier: str,
    value: Union[float, int, str, None],
    priority: Optional[int] = None,
) -> dict[str, Any]:
    address = await get_device_address(app, device_instance)
    obj_id = ObjectIdentifier(object_identifier)
    prop_id, prop_idx = parse_property_identifier(property_identifier)

    is_release = value is None or value == "null" or (
        isinstance(value, str) and value.strip().lower() == "null"
    )
    if is_release:
        if priority is None or not (1 <= int(priority) <= 16):
            raise BacnetOpsError("Null release requires priority 1–16")
        write_value: Any = Null(())
        write_priority = int(priority)
    else:
        write_value = value
        write_priority = int(priority) if priority is not None else None

    if write_priority is not None:
        result = await app.write_property(
            address, obj_id, prop_id, write_value, prop_idx, write_priority
        )
    else:
        result = await app.write_property(address, obj_id, prop_id, write_value, prop_idx)
    action = "released" if is_release else "written"
    return {
        "status": "success",
        "action": action,
        "device_instance": device_instance,
        "object_identifier": object_identifier,
        "property_identifier": property_identifier,
        "priority": write_priority,
        "response": str(result),
    }
