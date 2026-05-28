"""Shared BACnet discovery helpers (devices, points, full inventory)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from bacpypes3.apdu import AbortPDU, AbortReason, ErrorRejectAbortNack
from bacpypes3.app import Application
from bacpypes3.debugging import ModuleLogger, bacpypes_debugging
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier, ObjectType

try:
    from bacpypes3.errors import InvalidTag
except ImportError:
    InvalidTag = Exception  # type: ignore[misc, assignment]

_debug = 0
_log = ModuleLogger(globals())
show_warnings = False
_READ_ERRORS = (ErrorRejectAbortNack, InvalidTag)
_DISCOVER_PROPERTIES = ("object-name", "description", "present-value", "units")


def set_show_warnings(enabled: bool) -> None:
    global show_warnings
    show_warnings = enabled


def _warn(msg: str) -> None:
    if show_warnings:
        sys.stderr.write(msg)


def parse_limits(limits: list[int]) -> tuple[int, int]:
    if len(limits) == 1:
        return limits[0], limits[0]
    if len(limits) == 2:
        return limits[0], limits[1]
    raise ValueError("Provide one or two device instance limits.")


def write_csv(
    out_path: str | None,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    *,
    append: bool = False,
) -> None:
    if not out_path:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return

    out_p = Path(out_path)
    write_header = not (append and out_p.is_file() and out_p.stat().st_size > 0)
    with open(out_path, "a" if append else "w", newline="", encoding="utf-8") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    mode = "Appended" if append and not write_header else "Wrote"
    sys.stderr.write(f"{mode} {len(rows)} rows to {out_path}\n")


async def collect_i_ams(
    app: Application,
    low_limit: int,
    high_limit: int,
    *,
    router_ip: str | None = None,
    mstp_net: int | None = None,
    timeout: float = 10.0,
    local_too: bool = False,
) -> list[Any]:
    discovered: dict[int, Any] = {}

    if router_ip and mstp_net:
        mstp_broadcast = Address(f"{mstp_net}:*@{router_ip}")
        sys.stderr.write(f"Discovering MS/TP at {mstp_broadcast} ({low_limit}..{high_limit})...\n")
        mstp_i_ams = await app.who_is(
            low_limit, high_limit, address=mstp_broadcast, timeout=timeout
        )
        for i_am in mstp_i_ams or []:
            discovered[i_am.iAmDeviceIdentifier[1]] = i_am

    if local_too or not (router_ip and mstp_net):
        sys.stderr.write(f"Discovering BACnet/IP {low_limit}..{high_limit}...\n")
        local_i_ams = await app.who_is(
            low_limit,
            high_limit,
            address=Address("*") if local_too else None,
            timeout=timeout,
        )
        for i_am in local_i_ams or []:
            discovered[i_am.iAmDeviceIdentifier[1]] = i_am

    return list(discovered.values())


@bacpypes_debugging
async def safe_read_property(
    app: Application,
    address: Address,
    oid: ObjectIdentifier,
    prop: str,
):
    try:
        return await app.read_property(address, oid, prop)
    except _READ_ERRORS as err:
        _warn(f"  skip {oid} {prop}: {err}\n")
        return None
    except Exception as err:
        _warn(f"  skip {oid} {prop}: {err}\n")
        return None


def filter_point_objects(object_list: list[ObjectIdentifier]) -> list[ObjectIdentifier]:
    return [oid for oid in object_list if oid[0] != ObjectType.device]


@bacpypes_debugging
async def object_identifiers(
    app: Application, device_address: Address, device_identifier: ObjectIdentifier
) -> list[ObjectIdentifier]:
    try:
        full_list = await app.read_property(device_address, device_identifier, "object-list")
        return filter_point_objects(full_list)
    except AbortPDU as err:
        if err.apduAbortRejectReason not in (
            AbortReason.bufferOverflow,
            AbortReason.segmentationNotSupported,
        ):
            _warn(f"{device_identifier} object-list abort: {err}\n")
            return []
    except _READ_ERRORS as err:
        _warn(f"{device_identifier} object-list error: {err}\n")
        return []

    object_list: list[ObjectIdentifier] = []
    try:
        object_list_length = await app.read_property(
            device_address, device_identifier, "object-list", array_index=0
        )
        for i in range(int(object_list_length)):
            oid = await app.read_property(
                device_address,
                device_identifier,
                "object-list",
                array_index=i + 1,
            )
            object_list.append(oid)
    except _READ_ERRORS as err:
        _warn(f"{device_identifier} object-list length error: {err}\n")
    return filter_point_objects(object_list)


async def read_point_props(
    app: Application,
    address: Address,
    oid: ObjectIdentifier,
    vendor_info,  # noqa: ARG001
) -> dict[str, str]:
    row = {"object_name": "", "description": "", "present_value": "", "units": ""}
    for property_name in _DISCOVER_PROPERTIES:
        val = await safe_read_property(app, address, oid, property_name)
        if val is None:
            continue
        if property_name == "object-name":
            row["object_name"] = str(val)
        elif property_name == "description":
            row["description"] = str(val)
        elif property_name == "present-value":
            row["present_value"] = str(val)
        elif property_name == "units":
            row["units"] = str(val)
    return row
