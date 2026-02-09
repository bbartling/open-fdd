#!/usr/bin/env python3
"""
BACnet discovery → CSV config for driver.

Run to discover devices, trim CSV for points of interest, then use as config
for the BACnet driver in open_fdd.platform.drivers.bacnet.

Usage:
  python tools/discover_bacnet.py 3456789 -o config/bacnet_device.csv
  python tools/discover_bacnet.py 1 3456799 -o config/bacnet_devices.csv
  python tools/discover_bacnet.py 1234 --addr 192.168.1.50/24 -o config/bacnet.csv

Requires: pip install bacpypes3 ifaddr
"""
import sys
import asyncio
import csv
from typing import List, Optional, Any, Dict

try:
    from bacpypes3.debugging import bacpypes_debugging, ModuleLogger
    from bacpypes3.argparse import SimpleArgumentParser
    from bacpypes3.pdu import Address
    from bacpypes3.primitivedata import ObjectIdentifier
    from bacpypes3.basetypes import PropertyIdentifier
    from bacpypes3.apdu import AbortReason, AbortPDU, ErrorRejectAbortNack
    from bacpypes3.app import Application
    from bacpypes3.vendor import get_vendor_info
except ImportError:
    print("Requires: pip install bacpypes3 ifaddr")
    sys.exit(1)

_debug = 0
_log = ModuleLogger(globals())
show_warnings = False


@bacpypes_debugging
async def object_identifiers(app, device_address, device_identifier) -> List[ObjectIdentifier]:
    """Read object list from device."""
    try:
        object_list = await app.read_property(
            device_address, device_identifier, "object-list"
        )
        return object_list
    except AbortPDU as err:
        if err.apduAbortRejectReason in (
            AbortReason.bufferOverflow,
            AbortReason.segmentationNotSupported,
        ):
            pass
        else:
            if show_warnings:
                sys.stderr.write(f"{device_identifier} object-list abort: {err}\n")
            return []
    except ErrorRejectAbortNack as err:
        if show_warnings:
            sys.stderr.write(f"{device_identifier} object-list error/reject: {err}\n")
        return []

    object_list = []
    try:
        object_list_length = await app.read_property(
            device_address, device_identifier, "object-list", array_index=0
        )
        for i in range(object_list_length):
            oid = await app.read_property(
                device_address, device_identifier, "object-list", array_index=i + 1
            )
            object_list.append(oid)
    except ErrorRejectAbortNack as err:
        if show_warnings:
            sys.stderr.write(f"{device_identifier} object-list length error: {err}\n")
    return object_list


async def main() -> None:
    global show_warnings
    csv_rows: List[Dict[str, Any]] = []
    fieldnames = [
        "device_id", "object_identifier", "object_type", "object_instance",
        "object_name", "description", "present_value", "units",
    ]

    parser = SimpleArgumentParser()
    parser.add_argument("limits", type=int, nargs="+", help="device id or range (low high)")
    parser.add_argument("-o", "--output", help="output CSV file")
    wp = parser.add_mutually_exclusive_group(required=False)
    wp.add_argument("--warnings", dest="warnings", action="store_true")
    wp.add_argument("--no-warnings", dest="warnings", action="store_false")
    parser.set_defaults(warnings=False)
    args = parser.parse_args()

    show_warnings = args.warnings

    if len(args.limits) == 1:
        low_limit = high_limit = args.limits[0]
    elif len(args.limits) == 2:
        low_limit, high_limit = args.limits[0], args.limits[1]
    else:
        sys.stderr.write("Provide 1 or 2 device id arguments.\n")
        sys.exit(1)

    app = Application.from_args(args)
    try:
        sys.stderr.write(f"Discovering devices {low_limit} to {high_limit}...\n")
        i_ams = await app.who_is(low_limit, high_limit)
        if not i_ams:
            sys.stderr.write("No devices found.\n")
            sys.exit(1)

        sys.stderr.write(f"Found {len(i_ams)} device(s). Reading objects...\n")
        for i_am in i_ams:
            device_address = i_am.pduSource
            device_identifier = i_am.iAmDeviceIdentifier
            vendor_info = get_vendor_info(i_am.vendorID)
            sys.stderr.write(f" -> Processing {device_identifier}...\n")

            object_list = await object_identifiers(app, device_address, device_identifier)
            for object_identifier in object_list:
                row_data = {
                    "device_id": str(device_identifier),
                    "object_identifier": str(object_identifier),
                    "object_type": object_identifier[0],
                    "object_instance": object_identifier[1],
                    "object_name": "", "description": "", "present_value": "", "units": "",
                }
                object_class = vendor_info.get_object_class(object_identifier[0])
                if object_class is None:
                    csv_rows.append(row_data)
                    continue

                property_list: Optional[List[PropertyIdentifier]] = None
                try:
                    property_list = await app.read_property(
                        device_address, object_identifier, "property-list"
                    )
                except ErrorRejectAbortNack:
                    pass

                for property_name in ("object-name", "description", "present-value", "units"):
                    try:
                        prop_id = PropertyIdentifier(property_name)
                        if property_list and prop_id not in property_list:
                            continue
                        if object_class.get_property_type(prop_id) is None:
                            continue
                        pv = await app.read_property(
                            device_address, object_identifier, prop_id
                        )
                        pv_str = str(pv)
                        if "object at 0x" in pv_str and hasattr(pv, "get_value"):
                            try:
                                pv_str = str(pv.get_value())
                            except Exception:
                                pass
                        if property_name == "object-name":
                            row_data["object_name"] = pv_str
                        elif property_name == "description":
                            row_data["description"] = pv_str
                        elif property_name == "present-value":
                            row_data["present_value"] = pv_str
                        elif property_name == "units":
                            row_data["units"] = pv_str
                    except ErrorRejectAbortNack:
                        pass
                csv_rows.append(row_data)

        out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
        try:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
            sys.stderr.write("Done.\n")
        finally:
            if args.output:
                out.close()
    finally:
        app.close()


if __name__ == "__main__":
    asyncio.run(main())
