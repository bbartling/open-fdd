"""
BACnet Who-Is → devices-only CSV (no point object-list reads).

  python -m bacnet_toolshed.discover_devices 0 4194303 \\
    --name OpenFddEdge --instance 599999 --address 10.0.0.5/24:47808
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.primitivedata import ObjectIdentifier

from bacnet_toolshed.discover_lib import (
    collect_i_ams,
    parse_limits,
    safe_read_property,
    set_show_warnings,
    write_csv,
)
from bacnet_toolshed.paths import default_devices_discovered, ensure_layout

DEVICE_CSV_FIELDNAMES = [
    "device_instance",
    "device_address",
    "device_name",
    "model_name",
    "description",
    "vendor_id",
    "site_id",
    "building_id",
]


async def run_discover_devices(app_args) -> list[dict[str, Any]]:
    low, high = parse_limits(app_args.limits)
    set_show_warnings(bool(app_args.warnings))

    app = Application.from_args(app_args)
    rows: list[dict[str, Any]] = []
    try:
        i_ams = await collect_i_ams(
            app,
            low,
            high,
            router_ip=app_args.router_ip,
            mstp_net=app_args.mstp_net,
            timeout=app_args.timeout,
            local_too=app_args.local_too,
        )
        if not i_ams:
            sys.stderr.write("No devices found.\n")
            return []

        sys.stderr.write(f"Found {len(i_ams)} device(s). Reading device properties...\n")
        for i_am in i_ams:
            device_address = i_am.pduSource
            device_identifier: ObjectIdentifier = i_am.iAmDeviceIdentifier
            dev_inst = device_identifier[1]
            dev_addr = str(device_address)
            sys.stderr.write(f" -> {device_identifier} @ {dev_addr}\n")

            device_name = await safe_read_property(
                app, device_address, device_identifier, "object-name"
            )
            model_name = await safe_read_property(
                app, device_address, device_identifier, "model-name"
            )
            description = await safe_read_property(
                app, device_address, device_identifier, "description"
            )
            rows.append(
                {
                    "device_instance": str(dev_inst),
                    "device_address": dev_addr,
                    "device_name": str(device_name or ""),
                    "model_name": str(model_name or ""),
                    "description": str(description or ""),
                    "vendor_id": str(i_am.vendorID),
                    "site_id": app_args.site_id,
                    "building_id": app_args.building_id,
                }
            )

        rows.sort(key=lambda r: int(r["device_instance"]), reverse=True)

        out = app_args.output
        if not out:
            ensure_layout()
            out = str(default_devices_discovered())
        write_csv(out, DEVICE_CSV_FIELDNAMES, rows, append=bool(app_args.append))
        return rows
    finally:
        app.close()


def _build_parser() -> SimpleArgumentParser:
    parser = SimpleArgumentParser()
    parser.add_argument("limits", type=int, nargs="+", help="device id or range")
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--site-id", default="site")
    parser.add_argument("--building-id", default="building")
    parser.add_argument("--router-ip", default=None)
    parser.add_argument("--mstp-net", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--local-too", action="store_true")
    parser.add_argument("--append", action="store_true")
    warnings = parser.add_mutually_exclusive_group(required=False)
    warnings.add_argument("--warnings", dest="warnings", action="store_true")
    warnings.add_argument("--no-warnings", dest="warnings", action="store_false")
    parser.set_defaults(warnings=False)
    return parser


async def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        await run_discover_devices(args)
    except ValueError as err:
        sys.stderr.write(f"{err}\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
