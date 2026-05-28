"""
BACnet Who-Is discovery → full object inventory CSV (read-only commissioning).

  python -m bacnet_toolshed.discover 0 4194303 -o workspace/bacnet/commissioning/points_discovered.csv \\
    --site-id site1 --building-id bldg1 \\
    --name OpenFddEdge --instance 599999 --address 192.168.1.10/24:47808
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.primitivedata import ObjectIdentifier
from bacpypes3.vendor import get_vendor_info

from bacnet_toolshed.config import CSV_FIELDNAMES, normalize_row
from bacnet_toolshed.discover_lib import (
    collect_i_ams,
    object_identifiers,
    parse_limits,
    read_point_props,
    set_show_warnings,
    write_csv,
)
from bacnet_toolshed.paths import default_points_discovered, ensure_layout
from bacnet_toolshed.point_id import make_point_id


async def run_discover(
    low_limit: int,
    high_limit: int,
    *,
    output_path: str | None = None,
    site_id: str = "site",
    building_id: str = "building",
    router_ip: str | None = None,
    mstp_net: int | None = None,
    discover_timeout: float = 10.0,
    local_too: bool = False,
    append_csv: bool = False,
    app_args=None,
) -> list[dict[str, Any]]:
    parser = SimpleArgumentParser()
    parser.add_argument("limits", type=int, nargs="+", help="device id or range")
    parser.add_argument("-o", "--output", help="CSV output path")
    parser.add_argument("--site-id", default=site_id)
    parser.add_argument("--building-id", default=building_id)
    parser.add_argument("--router-ip", default=None)
    parser.add_argument("--mstp-net", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=discover_timeout)
    parser.add_argument("--local-too", action="store_true")
    parser.add_argument("--append", action="store_true")
    warnings_parser = parser.add_mutually_exclusive_group(required=False)
    warnings_parser.add_argument("--warnings", dest="warnings", action="store_true")
    warnings_parser.add_argument("--no-warnings", dest="warnings", action="store_false")
    parser.set_defaults(warnings=False)

    if app_args is None:
        app_args = parser.parse_args()
    set_show_warnings(bool(app_args.warnings))

    app = Application.from_args(app_args)
    csv_rows: list[dict[str, Any]] = []
    defaults = {"site_id": app_args.site_id, "building_id": app_args.building_id}

    try:
        i_ams = await collect_i_ams(
            app,
            low_limit,
            high_limit,
            router_ip=app_args.router_ip,
            mstp_net=app_args.mstp_net,
            timeout=app_args.timeout,
            local_too=app_args.local_too,
        )
        if not i_ams:
            sys.stderr.write("No devices found.\n")
            return []

        sys.stderr.write(f"Found {len(i_ams)} device(s).\n")
        for i_am in i_ams:
            device_address = i_am.pduSource
            device_identifier: ObjectIdentifier = i_am.iAmDeviceIdentifier
            vendor_info = get_vendor_info(i_am.vendorID)
            dev_inst = device_identifier[1]
            dev_addr = str(device_address)
            sys.stderr.write(f" -> {device_identifier} @ {dev_addr}\n")

            try:
                oids = await object_identifiers(app, device_address, device_identifier)
            except Exception as err:
                sys.stderr.write(f"  {device_identifier} object-list failed: {err}\n")
                continue

            for oid in oids:
                try:
                    props = await read_point_props(app, device_address, oid, vendor_info)
                except Exception as err:
                    sys.stderr.write(f"  skip {oid} on {device_identifier}: {err}\n")
                    continue
                raw = {
                    "device_instance": str(dev_inst),
                    "device_address": dev_addr,
                    "object_type": str(oid[0]),
                    "object_instance": str(oid[1]),
                    "object_name": props["object_name"],
                    "description": props["description"],
                    "present_value": props["present_value"],
                    "units": props["units"],
                    "site_id": app_args.site_id,
                    "building_id": app_args.building_id,
                    "system_id": "",
                    "brick_class": "",
                    "brick_tag": "",
                    "enabled": "0",
                    "poll_interval_s": "60",
                }
                raw["point_id"] = make_point_id(dev_inst, oid[0], oid[1])
                csv_rows.append(normalize_row(raw, defaults))

        out_path = output_path or getattr(app_args, "output", None)
        if not out_path:
            ensure_layout()
            out_path = str(default_points_discovered())
        do_append = append_csv or bool(getattr(app_args, "append", False))
        write_csv(out_path, CSV_FIELDNAMES, csv_rows, append=do_append)
        return csv_rows
    finally:
        app.close()


async def main() -> None:
    parser = SimpleArgumentParser()
    parser.add_argument("limits", type=int, nargs="+")
    parser.add_argument("-o", "--output")
    parser.add_argument("--site-id", default="site")
    parser.add_argument("--building-id", default="building")
    parser.add_argument("--router-ip", default=None)
    parser.add_argument("--mstp-net", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--local-too", action="store_true")
    parser.add_argument("--append", action="store_true")
    warnings_parser = parser.add_mutually_exclusive_group(required=False)
    warnings_parser.add_argument("--warnings", dest="warnings", action="store_true")
    warnings_parser.add_argument("--no-warnings", dest="warnings", action="store_false")
    parser.set_defaults(warnings=False)
    args = parser.parse_args()

    try:
        low, high = parse_limits(args.limits)
    except ValueError as err:
        sys.stderr.write(f"{err}\n")
        sys.exit(1)

    await run_discover(
        low,
        high,
        output_path=args.output,
        site_id=args.site_id,
        building_id=args.building_id,
        router_ip=args.router_ip,
        mstp_net=args.mstp_net,
        discover_timeout=args.timeout,
        local_too=args.local_too,
        append_csv=args.append,
        app_args=args,
    )


if __name__ == "__main__":
    asyncio.run(main())
