#!/usr/bin/env python3
"""BACpypes3 Who-Is / ReadProperty / sensor smoke for an OT LAN NIC.

Who-Is alone is not enough — peer IPs change on the test bench. Always follow
discovery with at least one unicast ReadProperty of a known sensor.

Mirrors the interactive shell workflow from:
  https://github.com/JoelBender/BACpypes3/discussions/125#discussioncomment-16177547

Examples:
  .venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py whois \\
    --address 192.168.204.11/24 --timeout 8

  .venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py read \\
    --address 192.168.204.11/24 --target 192.168.204.55 \\
    --object analog-value,1 --property present-value

  .venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py sensor \\
    --address 192.168.204.11/24 --target 192.168.204.55 \\
    --object analog-value,1 --expect-min 0 --expect-max 200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any


def _ipv4_host(source: str) -> str | None:
    """Extract IPv4 host from bacpypes source (strip port / MS/TP tokens)."""
    s = (source or "").strip()
    if not s or ":" in s and not re.match(r"^\d+\.\d+\.\d+\.\d+", s):
        # MS/TP-style "2000:7" or empty — not a unicast BIP target
        if re.match(r"^\d+:\d+$", s):
            return None
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+)(?::\d+)?$", s)
    return m.group(1) if m else None


async def _open_app(address: str, instance: int, name: str):
    from bacpypes3.argparse import SimpleArgumentParser
    from bacpypes3.app import Application

    argv = ["bacpypes3_ot_smoke", "--name", name, "--address", address, "--instance", str(instance)]
    args = SimpleArgumentParser().parse_args(argv[1:])
    return Application.from_args(args)


async def run_whois(
    address: str,
    instance: int,
    name: str,
    low: int | None,
    high: int | None,
    timeout: float,
) -> list[dict[str, Any]]:
    app = await _open_app(address, instance, name)
    try:
        try:
            i_ams = await asyncio.wait_for(app.who_is(low, high), timeout=timeout)
        except asyncio.TimeoutError:
            i_ams = []
        devices: list[dict[str, Any]] = []
        for iam in i_ams or []:
            try:
                device_id = iam.iAmDeviceIdentifier
                if isinstance(device_id, (tuple, list)) and len(device_id) >= 2:
                    inst = int(device_id[1])
                else:
                    inst = int(getattr(device_id, "instance", device_id))
            except Exception:
                inst = None
            src = str(getattr(iam, "pduSource", ""))
            devices.append(
                {
                    "device_instance": inst,
                    "source": src,
                    "ipv4": _ipv4_host(src),
                    "vendor_id": getattr(iam, "vendorID", None),
                    "max_apdu": getattr(iam, "maxAPDULengthAccepted", None),
                    "segmentation": str(getattr(iam, "segmentationSupported", "")),
                }
            )
        return devices
    finally:
        app.close()


async def run_read(
    address: str,
    instance: int,
    name: str,
    target: str,
    obj: str,
    prop: str,
    timeout: float,
) -> dict[str, Any]:
    app = await _open_app(address, instance, name)
    try:
        value = await asyncio.wait_for(
            app.read_property(target, obj, prop),
            timeout=timeout,
        )
        return {
            "ok": True,
            "target": target,
            "object": obj,
            "property": prop,
            "value": value if isinstance(value, (int, float, str, bool)) or value is None else str(value),
            "value_type": type(value).__name__,
        }
    except Exception as exc:
        return {
            "ok": False,
            "target": target,
            "object": obj,
            "property": prop,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        app.close()


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


async def run_sensor(
    address: str,
    instance: int,
    name: str,
    low: int | None,
    high: int | None,
    whois_timeout: float,
    read_timeout: float,
    target: str | None,
    obj: str,
    prop: str,
    expect_min: float | None,
    expect_max: float | None,
    min_devices: int,
) -> dict[str, Any]:
    devices = await run_whois(address, instance, name, low, high, whois_timeout)
    whois_ok = len(devices) >= min_devices
    resolved = target
    if not resolved:
        for d in devices:
            if d.get("ipv4"):
                resolved = d["ipv4"]
                break
    if not resolved:
        return {
            "ok": False,
            "whois_ok": whois_ok,
            "device_count": len(devices),
            "devices": devices,
            "error": "no IPv4 target: pass --target or ensure Who-Is returns a BIP peer",
        }

    read = await run_read(address, instance, f"{name}-Read", resolved, obj, prop, read_timeout)
    num = _numeric(read.get("value")) if read.get("ok") else None
    range_ok = True
    if read.get("ok") and num is not None:
        if expect_min is not None and num < expect_min:
            range_ok = False
        if expect_max is not None and num > expect_max:
            range_ok = False
    elif read.get("ok") and (expect_min is not None or expect_max is not None):
        range_ok = False

    ok = whois_ok and bool(read.get("ok")) and range_ok and num is not None
    return {
        "ok": ok,
        "whois_ok": whois_ok,
        "device_count": len(devices),
        "devices": devices,
        "target": resolved,
        "object": obj,
        "property": prop,
        "read": read,
        "numeric_value": num,
        "range_ok": range_ok,
        "expect_min": expect_min,
        "expect_max": expect_max,
    }


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--address",
        default="192.168.204.11/24",
        help="Local BACnet/IP bind address with prefix (default: Mint OT NIC)",
    )
    p.add_argument("--instance", type=int, default=59999, help="Local device instance for the probe")
    p.add_argument("--name", default="OpenFDD-BACnet-Smoke", help="Local device name")
    p.add_argument("--json", action="store_true", help="Print JSON only")


def main() -> int:
    p = argparse.ArgumentParser(
        description="BACpypes3 Who-Is / ReadProperty / sensor smoke on a bound BACnet/IP NIC"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pw = sub.add_parser("whois", help="Broadcast Who-Is and collect I-Am replies")
    _add_common(pw)
    pw.add_argument("--low", type=int, default=None)
    pw.add_argument("--high", type=int, default=None)
    pw.add_argument("--timeout", type=float, default=8.0)
    pw.add_argument("--min-devices", type=int, default=1)

    pr = sub.add_parser("read", help="Unicast ReadProperty (sensor present-value)")
    _add_common(pr)
    pr.add_argument("--target", required=True, help="Remote BIP address (IPv4, optional :port)")
    pr.add_argument("--object", default="analog-value,1", help="Object id e.g. analog-value,1")
    pr.add_argument("--property", default="present-value")
    pr.add_argument("--timeout", type=float, default=5.0)

    ps = sub.add_parser(
        "sensor",
        help="Who-Is then ReadProperty; assert numeric present-value (optional range)",
    )
    _add_common(ps)
    ps.add_argument("--low", type=int, default=None)
    ps.add_argument("--high", type=int, default=None)
    ps.add_argument("--whois-timeout", type=float, default=8.0)
    ps.add_argument("--read-timeout", type=float, default=5.0)
    ps.add_argument("--min-devices", type=int, default=1)
    ps.add_argument(
        "--target",
        default=None,
        help="BIP target; if omitted, first IPv4 peer from Who-Is",
    )
    ps.add_argument("--object", default="analog-value,1")
    ps.add_argument("--property", default="present-value")
    ps.add_argument("--expect-min", type=float, default=None)
    ps.add_argument("--expect-max", type=float, default=None)

    args = p.parse_args()

    if args.cmd == "whois":
        devices = asyncio.run(
            run_whois(args.address, args.instance, args.name, args.low, args.high, args.timeout)
        )
        payload: dict[str, Any] = {
            "ok": len(devices) >= args.min_devices,
            "mode": "whois",
            "address": args.address,
            "device_count": len(devices),
            "devices": devices,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Who-Is on {args.address}: {len(devices)} I-Am reply(ies)")
            for d in devices:
                print(
                    f"  device={d['device_instance']}  src={d['source']}  "
                    f"ipv4={d['ipv4']}  vendor={d['vendor_id']}"
                )
            print("PASS" if payload["ok"] else "FAIL")
        return 0 if payload["ok"] else 1

    if args.cmd == "read":
        payload = asyncio.run(
            run_read(
                args.address,
                args.instance,
                args.name,
                args.target,
                args.object,
                args.property,
                args.timeout,
            )
        )
        payload["mode"] = "read"
        payload["address"] = args.address
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            if payload["ok"]:
                print(
                    f"Read {args.target} {args.object}.{args.property} = {payload['value']}"
                )
                print("PASS")
            else:
                print(f"Read FAIL: {payload.get('error')}")
        return 0 if payload["ok"] else 1

    # sensor
    payload = asyncio.run(
        run_sensor(
            args.address,
            args.instance,
            args.name,
            args.low,
            args.high,
            args.whois_timeout,
            args.read_timeout,
            args.target,
            args.object,
            args.property,
            args.expect_min,
            args.expect_max,
            args.min_devices,
        )
    )
    payload["mode"] = "sensor"
    payload["address"] = args.address
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Who-Is: {payload['device_count']} device(s) ok={payload['whois_ok']}")
        for d in payload.get("devices") or []:
            print(
                f"  device={d['device_instance']}  src={d['source']}  ipv4={d['ipv4']}"
            )
        rd = payload.get("read") or {}
        if rd.get("ok"):
            print(
                f"Sensor read {payload.get('target')} {args.object}.{args.property} "
                f"= {rd.get('value')} (numeric={payload.get('numeric_value')} "
                f"range_ok={payload.get('range_ok')})"
            )
        else:
            print(f"Sensor read FAIL: {rd.get('error') or payload.get('error')}")
        print("PASS" if payload["ok"] else "FAIL")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
