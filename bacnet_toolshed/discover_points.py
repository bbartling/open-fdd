"""
Read BACnet points for each device listed in devices_discovered.csv.

  python -m bacnet_toolshed.discover_points \\
    --from-devices workspace/bacnet/commissioning/devices_discovered.csv \\
    --name OpenFddEdge --instance 599999 --address 10.0.0.5/24:47808
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path
from typing import Any, Sequence

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier
from bacpypes3.vendor import get_vendor_info

from bacnet_toolshed.config import CSV_FIELDNAMES, normalize_row
from bacnet_toolshed.discover_lib import object_identifiers, read_point_props, set_show_warnings, write_csv
from bacnet_toolshed.paths import default_points_discovered, ensure_layout
from bacnet_toolshed.point_id import make_point_id


async def discover_points_for_device(
    app: Application,
    dev: dict[str, str],
    *,
    site_id: str,
    building_id: str,
    defaults: dict[str, str],
) -> list[dict[str, str]]:
    try:
        dev_inst = int(str(dev.get("device_instance", "")).strip())
    except ValueError:
        _warn_skip(dev, "invalid device_instance")
        return []

    dev_addr = str(dev.get("device_address", "")).strip()
    if not dev_addr:
        _warn_skip(dev, "missing device_address")
        return []

    try:
        device_address = Address(dev_addr)
    except (TypeError, ValueError):
        _warn_skip(dev, "invalid device_address")
        return []
    device_identifier = ObjectIdentifier(("device", dev_inst))
    vendor_id = dev.get("vendor_id", "")
    try:
        vendor_info = get_vendor_info(int(vendor_id)) if str(vendor_id).strip() else None
    except (TypeError, ValueError):
        vendor_info = None

    sys.stderr.write(f" -> device,{dev_inst} @ {dev_addr}\n")
    try:
        oids = await object_identifiers(app, device_address, device_identifier)
    except Exception as err:
        sys.stderr.write(f"  object-list failed for {dev_inst}: {err}\n")
        return []

    device_rows: list[dict[str, str]] = []
    for oid in oids:
        try:
            props = await read_point_props(app, device_address, oid, vendor_info)
        except Exception as err:
            sys.stderr.write(f"  skip {oid}: {err}\n")
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
            "site_id": dev.get("site_id") or site_id,
            "building_id": dev.get("building_id") or building_id,
            "system_id": "",
            "brick_class": "",
            "brick_tag": "",
            "enabled": "0",
            "poll_interval_s": "60",
        }
        raw["point_id"] = make_point_id(dev_inst, oid[0], oid[1])
        device_rows.append(normalize_row(raw, defaults))
    return device_rows


def _write_per_device_csv(per_device_dir: Path, dev_inst: int, rows: Sequence[dict[str, str]]) -> Path:
    per_device_dir.mkdir(parents=True, exist_ok=True)
    out_path = per_device_dir / f"device_{dev_inst}.csv"
    write_csv(str(out_path), CSV_FIELDNAMES, list(rows), append=False)
    sys.stderr.write(f"  Wrote {len(rows)} points → {out_path.name}\n")
    return out_path


async def run_discover_points(app_args) -> list[dict[str, Any]]:
    set_show_warnings(bool(app_args.warnings))
    devices_path = Path(app_args.from_devices)
    if not devices_path.is_file():
        sys.stderr.write(f"Devices file not found: {devices_path}\n")
        sys.exit(1)

    per_device_dir: Path | None = None
    if getattr(app_args, "per_device_dir", None):
        per_device_dir = Path(app_args.per_device_dir)
        per_device_dir.mkdir(parents=True, exist_ok=True)

    app = Application.from_args(app_args)
    csv_rows: list[dict[str, Any]] = []
    defaults = {"site_id": app_args.site_id, "building_id": app_args.building_id}

    try:
        with devices_path.open(newline="", encoding="utf-8") as f:
            devices = list(csv.DictReader(f))

        if not devices:
            sys.stderr.write("No devices in CSV.\n")
            return []

        sys.stderr.write(f"Discovering points for {len(devices)} device(s)...\n")
        for dev in devices:
            device_rows = await discover_points_for_device(
                app,
                dev,
                site_id=app_args.site_id,
                building_id=app_args.building_id,
                defaults=defaults,
            )
            if per_device_dir and device_rows:
                dev_inst = int(device_rows[0]["device_instance"])
                _write_per_device_csv(per_device_dir, dev_inst, device_rows)
            csv_rows.extend(device_rows)

        out = app_args.output
        if out:
            write_csv(out, CSV_FIELDNAMES, csv_rows, append=bool(app_args.append))
        elif csv_rows:
            ensure_layout()
            write_csv(str(default_points_discovered()), CSV_FIELDNAMES, csv_rows, append=False)
        return csv_rows
    finally:
        app.close()


def _warn_skip(dev: dict[str, str], reason: str) -> None:
    inst = dev.get("device_instance", "?")
    sys.stderr.write(f"  skip device {inst}: {reason}\n")


def _build_parser() -> SimpleArgumentParser:
    parser = SimpleArgumentParser()
    parser.add_argument(
        "--from-devices",
        required=True,
        help="devices_discovered.csv from discover_devices",
    )
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument(
        "--per-device-dir",
        default=None,
        help="Write one CSV per device: device_<instance>.csv",
    )
    parser.add_argument("--site-id", default="site")
    parser.add_argument("--building-id", default="building")
    parser.add_argument("--append", action="store_true")
    warnings = parser.add_mutually_exclusive_group(required=False)
    warnings.add_argument("--warnings", dest="warnings", action="store_true")
    warnings.add_argument("--no-warnings", dest="warnings", action="store_false")
    parser.set_defaults(warnings=False)
    return parser


async def main() -> None:
    args = _build_parser().parse_args()
    await run_discover_points(args)


if __name__ == "__main__":
    asyncio.run(main())
