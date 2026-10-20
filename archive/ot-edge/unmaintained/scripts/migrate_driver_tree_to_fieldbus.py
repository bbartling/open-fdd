#!/usr/bin/env python3
"""Migrate legacy edge driver_tree.json into openfdd-fieldbus field_devices.toml snippets.

Reads a persisted Open-FDD driver tree (default:
``workspace/data/drivers/bacnet/driver_tree.json``) and emits:

1. ``field_devices.toml`` snippets for BACnet/IP devices (stdout or ``--out-toml``)
2. A migration report JSON listing unresolved Modbus/Haystack/JSON-API mappings

Usage:
  python3 scripts/migrate_driver_tree_to_fieldbus.py
  python3 scripts/migrate_driver_tree_to_fieldbus.py path/to/driver_tree.json
  python3 scripts/migrate_driver_tree_to_fieldbus.py --out-toml config/fieldbus/field_devices.migrated.toml
  python3 scripts/migrate_driver_tree_to_fieldbus.py --report /tmp/migration_report.json

The script accepts unified trees (``bacnet.devices``), registry trees
(``drivers[].id == bacnet-ip``), and compat exports that include a ``tree`` key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TREE = ROOT / "workspace" / "data" / "drivers" / "bacnet" / "driver_tree.json"


def load_tree(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return data


def parse_object_identifier(value: str) -> tuple[str, int] | None:
    if not value:
        return None
    if "," in value:
        obj_type, inst = value.split(",", 1)
        try:
            return obj_type.strip(), int(inst.strip())
        except ValueError:
            return None
    m = re.match(r"^([^:]+):(\d+)$", value)
    if m:
        return m.group(1), int(m.group(2))
    return None


def parse_host_port(address: str) -> tuple[str, int]:
    address = (address or "").strip()
    if not address:
        return "127.0.0.1", 0xBAC0
    if ":" in address:
        host, port_s = address.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return address, 0xBAC0
    return address, 0xBAC0


def bacnet_devices_from_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []

    if isinstance(tree.get("bacnet"), dict):
        raw = tree["bacnet"].get("devices")
        if isinstance(raw, list):
            devices.extend(raw)

    if not devices and isinstance(tree.get("devices"), list):
        devices.extend(tree["devices"])

    if not devices:
        drivers = tree.get("drivers")
        if isinstance(drivers, list):
            for driver in drivers:
                if not isinstance(driver, dict):
                    continue
                if driver.get("id") != "bacnet-ip":
                    continue
                devs = driver.get("devices")
                if isinstance(devs, list):
                    devices.extend(devs)

    nested = tree.get("tree")
    if not devices and isinstance(nested, dict):
        return bacnet_devices_from_tree(nested)

    return devices


def modbus_devices_from_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    if isinstance(tree.get("modbus"), dict):
        raw = tree["modbus"].get("devices")
        if isinstance(raw, list):
            devices.extend(raw)
    if not devices and isinstance(tree.get("modbus_devices"), list):
        devices.extend(tree["modbus_devices"])
    drivers = tree.get("drivers")
    if not devices and isinstance(drivers, list):
        for driver in drivers:
            if isinstance(driver, dict) and driver.get("id") == "modbus-tcp":
                devs = driver.get("devices")
                if isinstance(devs, list):
                    devices.extend(devs)
    nested = tree.get("tree")
    if not devices and isinstance(nested, dict):
        return modbus_devices_from_tree(nested)
    return devices


def haystack_devices_from_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    if isinstance(tree.get("haystack"), dict):
        raw = tree["haystack"].get("devices")
        if isinstance(raw, list):
            devices.extend(raw)
    if not devices and isinstance(tree.get("haystack_devices"), list):
        devices.extend(tree["haystack_devices"])
    nested = tree.get("tree")
    if not devices and isinstance(nested, dict):
        return haystack_devices_from_tree(nested)
    return devices


def json_api_sources_from_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if isinstance(tree.get("json_api"), dict):
        raw = tree["json_api"].get("devices")
        if isinstance(raw, list):
            sources.extend(raw)
    if not sources and isinstance(tree.get("json_api_devices"), list):
        sources.extend(tree["json_api_devices"])
    drivers = tree.get("drivers")
    if not sources and isinstance(drivers, list):
        for driver in drivers:
            if isinstance(driver, dict) and driver.get("id") == "json-api":
                srcs = driver.get("sources")
                if isinstance(srcs, list):
                    sources.extend(srcs)
    nested = tree.get("tree")
    if not sources and isinstance(nested, dict):
        return json_api_sources_from_tree(nested)
    return sources


def emit_field_device_toml(device: dict[str, Any], unresolved: list[dict[str, Any]]) -> str | None:
    inst = device.get("device_instance")
    if inst is None:
        unresolved.append({"reason": "missing device_instance", "device": device})
        return None
    try:
        device_instance = int(str(inst).strip('"'))
    except ValueError:
        unresolved.append({"reason": "invalid device_instance", "device": device})
        return None

    name = (
        device.get("device_name")
        or device.get("name")
        or f"device-{device_instance}"
    )
    if isinstance(name, dict):
        name = str(name)
    name = str(name).strip().replace(" ", "-") or f"device-{device_instance}"

    address = (
        device.get("device_address")
        or device.get("address")
        or ""
    )
    if isinstance(address, dict):
        address = address.get("value") or ""
    host, port = parse_host_port(str(address))

    lines = [
        "[[devices]]",
        f'name = "{name}"',
        "enabled = true",
        f"device_instance = {device_instance}",
        f'host = "{host}"',
        f"port = {port}",
    ]

    mstp_network = device.get("mstp_network")
    mstp_mac = device.get("mstp_mac")
    if mstp_network is not None:
        lines.append(f"mstp_network = {int(mstp_network)}")
    if isinstance(mstp_mac, list) and mstp_mac:
        mac_vals = ", ".join(str(int(x)) for x in mstp_mac)
        lines.append(f"mstp_mac = [{mac_vals}]")

    point_lines: list[str] = []
    points = device.get("points")
    if isinstance(points, list):
        for pt in points:
            if not isinstance(pt, dict):
                continue
            oid = (
                pt.get("object_identifier")
                or pt.get("point_id")
                or pt.get("id")
                or ""
            )
            parsed = parse_object_identifier(str(oid))
            if not parsed:
                unresolved.append(
                    {
                        "reason": "unmapped bacnet point",
                        "device_instance": device_instance,
                        "point": pt,
                    }
                )
                continue
            obj_type, obj_inst = parsed
            point_name = (
                pt.get("object_name")
                or pt.get("name")
                or pt.get("label")
                or f"{obj_type}-{obj_inst}"
            )
            if isinstance(point_name, dict):
                point_name = str(point_name)
            point_name = str(point_name).strip().replace(" ", "-")
            units = pt.get("units") or pt.get("unit") or ""
            if isinstance(units, dict):
                units = ""
            units = str(units).replace('"', '\\"')
            point_lines.append(
                "  { "
                f'object_type = "{obj_type}", object_instance = {obj_inst}, '
                f'point_name = "{point_name}", units = "{units}" '
                "},"
            )

    if point_lines:
        lines.append("points = [")
        lines.extend(point_lines)
        lines.append("]")
    else:
        unresolved.append(
            {
                "reason": "device has no mappable BACnet points",
                "device_instance": device_instance,
                "device": device,
            }
        )

    lines.append("")
    return "\n".join(lines)


def hosted_device_id(value: Any) -> str | None:
    inst = str(value).strip().strip('"')
    if inst in {"599999", "599_999"}:
        return inst
    return None


def build_report(tree_path: Path, tree: dict[str, Any]) -> dict[str, Any]:
    unresolved: list[dict[str, Any]] = []
    fatal_unresolved: list[dict[str, Any]] = []
    toml_blocks: list[str] = []
    hosted_entries = 0

    bacnet_devices = bacnet_devices_from_tree(tree)
    for dev in bacnet_devices:
        if not isinstance(dev, dict):
            continue
        # Skip local Open-FDD hosted device (fieldbus hosts 599999 separately).
        inst = hosted_device_id(dev.get("device_instance"))
        if inst is not None:
            hosted_entries += 1
            points = dev.get("points")
            point_count = len(points) if isinstance(points, list) else 0
            if hosted_entries > 1:
                entry = {
                    "severity": "fatal",
                    "reason": "duplicate hosted server device 599999 in driver tree — breaks fieldbus hosting",
                    "device_instance": inst,
                    "device": dev,
                }
                unresolved.append(entry)
                fatal_unresolved.append(entry)
                continue
            if point_count > 0:
                entry = {
                    "severity": "fatal",
                    "reason": "driver tree maps BACnet points onto hosted server 599999 — conflict with fieldbus objects.csv",
                    "device_instance": inst,
                    "point_count": point_count,
                }
                unresolved.append(entry)
                fatal_unresolved.append(entry)
                continue
            unresolved.append(
                {
                    "severity": "info",
                    "reason": "skipped local server device — configure hosted objects in fieldbus objects.csv",
                    "device_instance": inst,
                }
            )
            continue
        block = emit_field_device_toml(dev, unresolved)
        if block:
            toml_blocks.append(block)

    modbus_devices = modbus_devices_from_tree(tree)
    for dev in modbus_devices:
        unresolved.append(
            {
                "protocol": "modbus-tcp",
                "reason": "manual mapping required — set MODBUS_DEFAULT_HOST in fieldbus config or extend field_devices schema",
                "device": dev,
            }
        )

    for dev in haystack_devices_from_tree(tree):
        unresolved.append(
            {
                "protocol": "haystack",
                "reason": "configure HAYSTACK_BASE_URL / credentials in openfdd-fieldbus config",
                "device": dev,
            }
        )

    for src in json_api_sources_from_tree(tree):
        unresolved.append(
            {
                "protocol": "json-api",
                "reason": "JSON API sources remain on edge until central command path is defined",
                "source": src,
            }
        )

    return {
        "ok": len(fatal_unresolved) == 0,
        "source": str(tree_path),
        "bacnet_devices_found": len(bacnet_devices),
        "field_devices_toml_blocks": len(toml_blocks),
        "field_devices_toml": "\n".join(toml_blocks).rstrip() + ("\n" if toml_blocks else ""),
        "unresolved": unresolved,
        "fatal_unresolved": fatal_unresolved,
        "next_steps": [
            "Review emitted TOML and merge into config/fieldbus/field_devices.toml",
            "Resolve unresolved[] entries manually",
            "Run scripts/gates/architecture_no_central_fieldwire.sh",
            "Start openfdd-fieldbus and verify MQTTS telemetry on openfdd-central",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "driver_tree",
        nargs="?",
        default=str(DEFAULT_TREE),
        help=f"path to driver_tree.json (default: {DEFAULT_TREE})",
    )
    parser.add_argument(
        "--out-toml",
        type=Path,
        help="write field_devices.toml snippet to this path",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="write migration report JSON to this path (default: stdout JSON if no --out-toml)",
    )
    args = parser.parse_args()

    tree_path = Path(args.driver_tree)
    if not tree_path.is_file():
        print(f"driver tree not found: {tree_path}", file=sys.stderr)
        return 1

    tree = load_tree(tree_path)
    report = build_report(tree_path, tree)

    if args.out_toml:
        args.out_toml.parent.mkdir(parents=True, exist_ok=True)
        args.out_toml.write_text(report["field_devices_toml"], encoding="utf-8")
        print(f"wrote {args.out_toml}", file=sys.stderr)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.report}", file=sys.stderr)
    elif not args.out_toml:
        print(json.dumps(report, indent=2))

    if not args.out_toml and not args.report:
        if report["field_devices_toml"]:
            print("\n# --- field_devices.toml snippet ---\n", file=sys.stderr)
            print(report["field_devices_toml"], file=sys.stderr)

    if report.get("fatal_unresolved"):
        print(
            f"fatal: {len(report['fatal_unresolved'])} unresolved 599999 hosting conflict(s)",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
